#include "pvm/runtime.hpp"

#ifndef PVM_USE_OPENSSL
#define PVM_USE_OPENSSL 1
#endif

#if PVM_USE_OPENSSL
#include <openssl/evp.h>
#include <openssl/pem.h>
#endif

#include <algorithm>
#include <array>
#include <cstdio>
#include <cstring>
#include <deque>
#include <fstream>
#include <limits>
#include <optional>
#include <set>
#include <sstream>
#include <unordered_map>
#include <utility>

namespace pvm {
namespace {

constexpr std::size_t kMaximumModuleBytes = 16U * 1024U * 1024U;
constexpr std::size_t kMaximumTableEntries = 65535;
constexpr std::size_t kMaximumUiDepth = 64;

enum class Op : std::uint8_t {
  Constant = 1,
  StateGet = 4,
  StateSet = 5,
  IntegerAdd = 6,
  Equal = 7,
  Jump = 8,
  JumpIfFalse = 9,
  Effect = 10,
  Pop = 11,
  Render = 12,
  Halt = 13,
  AsyncEffect = 14,
  EventValue = 15,
};

struct Limits {
  std::uint32_t max_instructions_per_event;
  std::uint32_t max_stack;
  std::uint32_t max_state_bytes;
  std::uint32_t max_ui_nodes;
  std::uint32_t max_tasks;
};

struct Instruction {
  Op op;
  Value value{std::int64_t{0}};
  std::uint32_t first{0};
  std::uint32_t second{0};
  std::uint8_t argument_count{0};
};

struct Segment {
  std::uint8_t kind;
  std::uint16_t index;
};

struct PropertyExpression {
  PropertyKey key;
  std::vector<Segment> segments;
};

struct UiNode {
  NodeType type;
  std::uint32_t id;
  std::vector<PropertyExpression> properties;
  std::vector<EventBinding> events;
  std::vector<UiNode> children;
};

struct Module {
  std::uint16_t format;
  std::uint16_t minimum_runtime;
  std::uint64_t release;
  std::uint8_t profile;
  std::uint8_t platform;
  std::string module_id;
  std::string application_id;
  std::string tenant;
  std::string channel;
  std::uint64_t state_schema;
  std::uint32_t key_version;
  Limits limits;
  std::vector<std::string> capabilities;
  std::vector<std::uint16_t> capability_versions;
  std::vector<std::string> domains;
  std::vector<std::string> storage_scopes;
  std::vector<std::string> constants;
  std::vector<std::uint64_t> state_ids;
  std::vector<Value> initial_state;
  std::vector<std::vector<Instruction>> handlers;
  std::vector<UiNode> pages;
  std::uint16_t entry_page;
  std::optional<std::uint16_t> entry_handler;
};

class Reader {
 public:
  Reader(const std::uint8_t* data, std::size_t size) : data_(data), size_(size) {}

  std::uint8_t u8() {
    require(1);
    return data_[position_++];
  }

  std::uint16_t u16() {
    require(2);
    const auto result = static_cast<std::uint16_t>(data_[position_]) |
                        (static_cast<std::uint16_t>(data_[position_ + 1]) << 8U);
    position_ += 2;
    return result;
  }

  std::uint32_t u32() {
    require(4);
    std::uint32_t result = 0;
    for (unsigned shift = 0; shift < 32; shift += 8) {
      result |= static_cast<std::uint32_t>(data_[position_++]) << shift;
    }
    return result;
  }

  std::uint64_t u64() {
    require(8);
    std::uint64_t result = 0;
    for (unsigned shift = 0; shift < 64; shift += 8) {
      result |= static_cast<std::uint64_t>(data_[position_++]) << shift;
    }
    return result;
  }

  std::int64_t i64() {
    const auto bits = u64();
    std::int64_t value = 0;
    static_assert(sizeof(value) == sizeof(bits), "unexpected integer size");
    std::memcpy(&value, &bits, sizeof(value));
    return value;
  }

  std::string text() {
    const auto length = u16();
    require(length);
    std::string result(reinterpret_cast<const char*>(data_ + position_), length);
    position_ += length;
    return result;
  }

  const std::uint8_t* bytes(std::size_t length) {
    require(length);
    const auto* result = data_ + position_;
    position_ += length;
    return result;
  }

  bool empty() const { return position_ == size_; }
  std::size_t remaining() const { return size_ - position_; }

 private:
  void require(std::size_t length) {
    if (length > size_ - position_) {
      throw RuntimeError("truncated module");
    }
  }

  const std::uint8_t* data_;
  std::size_t size_;
  std::size_t position_{0};
};

std::vector<std::uint8_t> read_file(const std::string& path, std::size_t maximum) {
  std::ifstream input(path, std::ios::binary | std::ios::ate);
  if (!input) {
    throw RuntimeError("cannot open file: " + path);
  }
  const auto end = input.tellg();
  if (end < 0 || static_cast<std::uint64_t>(end) > maximum) {
    throw RuntimeError("file exceeds allowed size: " + path);
  }
  std::vector<std::uint8_t> bytes(static_cast<std::size_t>(end));
  input.seekg(0);
  if (!bytes.empty() &&
      !input.read(reinterpret_cast<char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()))) {
    throw RuntimeError("cannot read file: " + path);
  }
  return bytes;
}

void expect_magic(Reader& reader, const char* magic) {
  const auto* bytes = reader.bytes(4);
  if (!std::equal(bytes, bytes + 4, reinterpret_cast<const std::uint8_t*>(magic))) {
    throw RuntimeError("invalid module magic");
  }
}

void verify_ed25519(const std::uint8_t* payload, std::size_t payload_size,
                    const std::uint8_t* signature, std::size_t signature_size,
                    const std::string& public_key_path,
                    const SignatureVerifier& verifier) {
  if (signature_size != 64) {
    throw RuntimeError("invalid Ed25519 signature size");
  }
  if (verifier) {
    if (!verifier(payload, payload_size, signature, signature_size, public_key_path)) {
      throw RuntimeError("module signature verification failed");
    }
    return;
  }
#if PVM_USE_OPENSSL
  FILE* file = std::fopen(public_key_path.c_str(), "rb");
  if (file == nullptr) {
    throw RuntimeError("cannot open public key: " + public_key_path);
  }
  EVP_PKEY* raw_key = PEM_read_PUBKEY(file, nullptr, nullptr, nullptr);
  std::fclose(file);
  if (raw_key == nullptr) {
    throw RuntimeError("cannot parse public key");
  }
  std::unique_ptr<EVP_PKEY, decltype(&EVP_PKEY_free)> key(raw_key, EVP_PKEY_free);
  if (EVP_PKEY_base_id(key.get()) != EVP_PKEY_ED25519) {
    throw RuntimeError("public key is not Ed25519");
  }
  EVP_MD_CTX* raw_context = EVP_MD_CTX_new();
  if (raw_context == nullptr) {
    throw RuntimeError("cannot allocate signature verifier");
  }
  std::unique_ptr<EVP_MD_CTX, decltype(&EVP_MD_CTX_free)> context(raw_context, EVP_MD_CTX_free);
  if (EVP_DigestVerifyInit(context.get(), nullptr, nullptr, nullptr, key.get()) != 1 ||
      EVP_DigestVerify(context.get(), signature, signature_size, payload, payload_size) != 1) {
    throw RuntimeError("module signature verification failed");
  }
#else
  static_cast<void>(payload);
  static_cast<void>(payload_size);
  static_cast<void>(signature);
  static_cast<void>(public_key_path);
  throw RuntimeError("no signature verifier is installed");
#endif
}

ValueType value_type(const Value& value) {
  if (std::holds_alternative<std::int64_t>(value)) {
    return ValueType::Integer;
  }
  if (std::holds_alternative<bool>(value)) {
    return ValueType::Boolean;
  }
  return ValueType::String;
}

Value read_typed_value(Reader& reader, ValueType type, const std::vector<std::string>& constants) {
  switch (type) {
    case ValueType::Integer:
      return reader.i64();
    case ValueType::Boolean: {
      const auto raw = reader.u8();
      if (raw > 1) {
        throw RuntimeError("invalid boolean");
      }
      return raw == 1;
    }
    case ValueType::String: {
      const auto index = reader.u16();
      if (index >= constants.size()) {
        throw RuntimeError("constant index is out of range");
      }
      return constants[index];
    }
  }
  throw RuntimeError("invalid value type");
}

ValueType read_value_type(Reader& reader) {
  const auto raw = reader.u8();
  if (raw < static_cast<std::uint8_t>(ValueType::Integer) ||
      raw > static_cast<std::uint8_t>(ValueType::String)) {
    throw RuntimeError("invalid value type");
  }
  return static_cast<ValueType>(raw);
}

template <typename Enum>
Enum checked_enum(std::uint8_t raw, std::uint8_t minimum, std::uint8_t maximum, const char* label) {
  if (raw < minimum || raw > maximum) {
    throw RuntimeError(std::string("invalid ") + label);
  }
  return static_cast<Enum>(raw);
}

std::vector<std::string> read_text_table(Reader& reader) {
  const auto count = reader.u16();
  std::vector<std::string> result;
  result.reserve(count);
  for (std::size_t i = 0; i < count; ++i) {
    result.push_back(reader.text());
  }
  return result;
}

Instruction read_instruction(Reader& reader, const Module& module) {
  Instruction instruction;
  const auto raw_op = reader.u8();
  const auto maximum_op = module.format >= 5 ? 15 : (module.format >= 2 ? 14 : 13);
  if (raw_op != 1 && (raw_op < 4 || raw_op > maximum_op)) {
    throw RuntimeError("invalid opcode");
  }
  instruction.op = static_cast<Op>(raw_op);
  switch (instruction.op) {
    case Op::Constant: {
      const auto type = read_value_type(reader);
      instruction.value = read_typed_value(reader, type, module.constants);
      break;
    }
    case Op::EventValue:
      break;
    case Op::StateGet:
    case Op::StateSet:
      instruction.first = reader.u16();
      if (instruction.first >= module.initial_state.size()) {
        throw RuntimeError("state index is out of range");
      }
      break;
    case Op::Jump:
    case Op::JumpIfFalse:
      instruction.first = reader.u32();
      break;
    case Op::Effect:
    case Op::AsyncEffect:
      instruction.first = reader.u16();
      instruction.second = reader.u16();
      instruction.argument_count = reader.u8();
      if (instruction.first >= module.capabilities.size() ||
          instruction.second >= module.constants.size() || instruction.argument_count > 32) {
        throw RuntimeError("invalid effect instruction");
      }
      break;
    case Op::Render:
      instruction.first = reader.u16();
      break;
    case Op::IntegerAdd:
    case Op::Equal:
    case Op::Pop:
    case Op::Halt:
      break;
  }
  return instruction;
}

UiNode read_node(Reader& reader, Module& module, std::size_t depth, std::size_t& node_count,
                 std::set<std::uint32_t>& node_ids) {
  if (depth > kMaximumUiDepth || ++node_count > module.limits.max_ui_nodes) {
    throw RuntimeError("UI tree exceeds its resource budget");
  }
  UiNode node;
  node.type = checked_enum<NodeType>(reader.u8(), 1, 11, "node type");
  node.id = reader.u32();
  if (node.id == 0 || !node_ids.insert(node.id).second) {
    throw RuntimeError("duplicate or zero UI node id");
  }
  const auto property_count = reader.u16();
  node.properties.reserve(property_count);
  std::set<std::uint8_t> property_keys;
  for (std::size_t i = 0; i < property_count; ++i) {
    PropertyExpression expression;
    const auto raw_key = reader.u8();
    expression.key = checked_enum<PropertyKey>(raw_key, 1, 6, "property key");
    if (!property_keys.insert(raw_key).second) {
      throw RuntimeError("duplicate UI property");
    }
    const auto segment_count = reader.u16();
    if (segment_count == 0 || segment_count > 1024) {
      throw RuntimeError("invalid UI expression");
    }
    expression.segments.reserve(segment_count);
    for (std::size_t j = 0; j < segment_count; ++j) {
      Segment segment{reader.u8(), reader.u16()};
      if ((segment.kind == 1 && segment.index >= module.constants.size()) ||
          (segment.kind == 2 && segment.index >= module.initial_state.size()) ||
          (segment.kind != 1 && segment.kind != 2)) {
        throw RuntimeError("invalid UI expression segment");
      }
      expression.segments.push_back(segment);
    }
    node.properties.push_back(std::move(expression));
  }
  const auto event_count = reader.u16();
  node.events.reserve(event_count);
  std::set<std::uint8_t> event_types;
  for (std::size_t i = 0; i < event_count; ++i) {
    const auto raw_event = reader.u8();
    EventBinding binding{checked_enum<EventType>(raw_event, 1, 4, "event type"), reader.u16()};
    if (binding.handler >= module.handlers.size() || !event_types.insert(raw_event).second) {
      throw RuntimeError("invalid or duplicate event binding");
    }
    node.events.push_back(binding);
  }
  const auto child_count = reader.u16();
  node.children.reserve(child_count);
  for (std::size_t i = 0; i < child_count; ++i) {
    node.children.push_back(read_node(reader, module, depth + 1, node_count, node_ids));
  }
  return node;
}

void validate_handler(const Module& module, const std::vector<Instruction>& instructions) {
  if (instructions.empty() || instructions.size() > 1'000'000) {
    throw RuntimeError("invalid handler size");
  }
  using Stack = std::vector<ValueType>;
  std::vector<std::optional<Stack>> incoming(instructions.size());
  incoming[0] = Stack{};
  std::deque<std::size_t> queue{0};
  std::vector<bool> visited(instructions.size(), false);
  while (!queue.empty()) {
    const auto pc = queue.front();
    queue.pop_front();
    visited[pc] = true;
    auto stack = *incoming[pc];
    const auto& instruction = instructions[pc];
    auto pop = [&](std::optional<ValueType> expected = std::nullopt) {
      if (stack.empty()) {
        throw RuntimeError("bytecode stack underflow");
      }
      const auto actual = stack.back();
      stack.pop_back();
      if (expected && actual != *expected) {
        throw RuntimeError("bytecode stack type mismatch");
      }
      return actual;
    };

    switch (instruction.op) {
      case Op::Constant:
        stack.push_back(value_type(instruction.value));
        break;
      case Op::EventValue:
        stack.push_back(ValueType::String);
        break;
      case Op::StateGet:
        stack.push_back(value_type(module.initial_state[instruction.first]));
        break;
      case Op::StateSet:
        pop(value_type(module.initial_state[instruction.first]));
        break;
      case Op::IntegerAdd:
        pop(ValueType::Integer);
        pop(ValueType::Integer);
        stack.push_back(ValueType::Integer);
        break;
      case Op::Equal: {
        const auto right = pop();
        if (pop() != right) {
          throw RuntimeError("equality operands have different types");
        }
        stack.push_back(ValueType::Boolean);
        break;
      }
      case Op::JumpIfFalse:
        pop(ValueType::Boolean);
        break;
      case Op::Effect:
      case Op::AsyncEffect:
        for (std::size_t i = 0; i < instruction.argument_count; ++i) {
          pop();
        }
        stack.push_back(ValueType::String);
        break;
      case Op::Pop:
        pop();
        break;
      case Op::Render:
        if (instruction.first >= module.pages.size()) {
          throw RuntimeError("render page index is out of range");
        }
        break;
      case Op::Halt:
        if (!stack.empty()) {
          throw RuntimeError("handler leaves values on its stack");
        }
        break;
      case Op::Jump:
        break;
    }
    if (stack.size() > module.limits.max_stack) {
      throw RuntimeError("handler exceeds its stack budget");
    }

    std::array<std::size_t, 2> successors{};
    std::size_t successor_count = 0;
    if (instruction.op == Op::Jump) {
      successors[successor_count++] = instruction.first;
    } else if (instruction.op == Op::JumpIfFalse) {
      successors[successor_count++] = instruction.first;
      successors[successor_count++] = pc + 1;
    } else if (instruction.op != Op::Halt) {
      successors[successor_count++] = pc + 1;
    }
    for (std::size_t i = 0; i < successor_count; ++i) {
      const auto target = successors[i];
      if (target >= instructions.size()) {
        throw RuntimeError("jump target is out of range");
      }
      if (incoming[target] && *incoming[target] != stack) {
        throw RuntimeError("branches have incompatible stack shapes");
      }
      if (!incoming[target]) {
        incoming[target] = stack;
        queue.push_back(target);
      }
    }
  }
  if (std::find(visited.begin(), visited.end(), true) == visited.end()) {
    throw RuntimeError("handler has no reachable instructions");
  }
}

Module parse_payload(const std::uint8_t* payload, std::size_t payload_size,
                     const std::string& expected_application_id,
                     const std::string& expected_channel,
                     const std::string& expected_platform,
                     const std::string& expected_profile, std::uint64_t minimum_release) {
  Reader reader(payload, payload_size);
  expect_magic(reader, "PVBC");
  const auto format = reader.u16();
  if (format != 1 && format != 2 && format != 3 && format != 4 && format != 5) {
    throw RuntimeError("unsupported bytecode format");
  }
  Module module;
  module.format = format;
  module.minimum_runtime = reader.u16();
  if (module.minimum_runtime > kRuntimeVersion) {
    throw RuntimeError("module requires a newer runtime");
  }
  module.release = reader.u64();
  module.profile = reader.u8();
  module.platform = reader.u8();
  if (module.profile < 1 || module.profile > 4 || module.platform < 1 || module.platform > 4) {
    throw RuntimeError("invalid delivery metadata");
  }
  module.module_id = reader.text();
  module.application_id = reader.text();
  module.tenant = reader.text();
  module.channel = reader.text();
  module.state_schema = reader.u64();
  module.key_version = reader.u32();
  if (module.release == 0) {
    throw RuntimeError("invalid module release");
  }
  if (module.minimum_runtime < module.format) {
    throw RuntimeError("minimum runtime is older than the bytecode format");
  }
  if (module.application_id != expected_application_id) {
    throw RuntimeError("module application binding mismatch");
  }
  if (!expected_channel.empty() && module.channel != expected_channel) {
    throw RuntimeError("module channel binding mismatch");
  }
  static constexpr std::array<const char*, 4> profiles{
      "offline_sealed",
      "online_provisioned",
      "store_on_demand",
      "enterprise_managed",
  };
  static constexpr std::array<const char*, 4> platforms{
      "android",
      "ios",
      "harmonyos",
      "desktop",
  };
  if (!expected_platform.empty() && expected_platform != platforms.at(module.platform - 1)) {
    throw RuntimeError("module platform binding mismatch");
  }
  if (!expected_profile.empty() && expected_profile != profiles.at(module.profile - 1)) {
    throw RuntimeError("module delivery profile binding mismatch");
  }
  if (module.release < minimum_release) {
    throw RuntimeError("module rejected by anti-rollback policy");
  }
  if (module.state_schema == 0 || module.key_version == 0) {
    throw RuntimeError("invalid schema or key version");
  }
  module.limits = {
      reader.u32(),
      reader.u32(),
      reader.u32(),
      reader.u32(),
      format >= 2 ? reader.u32() : 64,
  };
  if (module.limits.max_instructions_per_event == 0 || module.limits.max_stack == 0 ||
      module.limits.max_state_bytes == 0 || module.limits.max_ui_nodes == 0 ||
      module.limits.max_tasks == 0 ||
      module.limits.max_instructions_per_event > 10'000'000 ||
      module.limits.max_stack > 10'000'000 ||
      module.limits.max_state_bytes > 10'000'000 ||
      module.limits.max_ui_nodes > 10'000'000 ||
      module.limits.max_tasks > 10'000'000) {
    throw RuntimeError("invalid resource budget");
  }
  module.capabilities = read_text_table(reader);
  module.capability_versions.assign(module.capabilities.size(), 1);
  if (format >= 3) {
    for (auto& version : module.capability_versions) {
      version = reader.u16();
      if (version == 0) {
        throw RuntimeError("invalid capability version");
      }
    }
  }
  module.domains = read_text_table(reader);
  module.storage_scopes = read_text_table(reader);
  module.constants = read_text_table(reader);
  if (module.capabilities.size() > 4096 || module.domains.size() > 4096 ||
      module.storage_scopes.size() > 4096 || module.constants.size() > kMaximumTableEntries) {
    throw RuntimeError("module table exceeds hard limit");
  }
  const auto require_unique = [](const std::vector<std::string>& values, const char* name) {
    if (std::set<std::string>(values.begin(), values.end()).size() != values.size()) {
      throw RuntimeError(std::string(name) + " table contains duplicates");
    }
  };
  require_unique(module.capabilities, "capability");
  require_unique(module.domains, "network domain");
  require_unique(module.storage_scopes, "storage scope");
  require_unique(module.constants, "constant");

  const auto state_count = reader.u16();
  if (state_count > 4096) {
    throw RuntimeError("state table exceeds hard limit");
  }
  if (format >= 4) {
    module.state_ids.reserve(state_count);
  }
  module.initial_state.reserve(state_count);
  std::size_t state_bytes = 0;
  for (std::size_t i = 0; i < state_count; ++i) {
    if (format >= 4) {
      const auto state_id = reader.u64();
      if (state_id == 0 ||
          std::find(module.state_ids.begin(), module.state_ids.end(), state_id) !=
              module.state_ids.end()) {
        throw RuntimeError("invalid or duplicate state persistence ID");
      }
      module.state_ids.push_back(state_id);
    }
    const auto type = read_value_type(reader);
    auto value = read_typed_value(reader, type, module.constants);
    state_bytes += type == ValueType::String ? std::get<std::string>(value).size() : 8;
    if (state_bytes > module.limits.max_state_bytes) {
      throw RuntimeError("initial state exceeds its resource budget");
    }
    module.initial_state.push_back(std::move(value));
  }

  const auto handler_count = reader.u16();
  module.handlers.resize(handler_count);
  for (auto& handler : module.handlers) {
    const auto instruction_count = reader.u32();
    if (instruction_count == 0 || instruction_count > 1'000'000) {
      throw RuntimeError("invalid instruction table size");
    }
    handler.reserve(instruction_count);
    for (std::size_t i = 0; i < instruction_count; ++i) {
      handler.push_back(read_instruction(reader, module));
    }
  }

  const auto page_count = reader.u16();
  if (page_count == 0) {
    throw RuntimeError("module has no pages");
  }
  std::size_t node_count = 0;
  std::set<std::uint32_t> node_ids;
  module.pages.reserve(page_count);
  for (std::size_t i = 0; i < page_count; ++i) {
    module.pages.push_back(read_node(reader, module, 1, node_count, node_ids));
  }
  module.entry_page = reader.u16();
  const auto entry_handler = reader.u16();
  if (module.entry_page >= module.pages.size() ||
      (entry_handler != 0xFFFF && entry_handler >= module.handlers.size())) {
    throw RuntimeError("invalid entry point");
  }
  if (entry_handler != 0xFFFF) {
    module.entry_handler = entry_handler;
  }
  if (!reader.empty()) {
    throw RuntimeError("unexpected trailing bytecode");
  }
  for (const auto& handler : module.handlers) {
    validate_handler(module, handler);
  }
  return module;
}

Module parse_package(const std::vector<std::uint8_t>& package,
                     const std::string& public_key_path,
                     const std::string& expected_application_id,
                     const std::string& expected_channel,
                     const std::string& expected_platform,
                     const std::string& expected_profile,
                     std::uint64_t minimum_release,
                     const SignatureVerifier& signature_verifier) {
  if (package.size() > kMaximumModuleBytes) {
    throw RuntimeError("package exceeds allowed size");
  }
  Reader reader(package.data(), package.size());
  expect_magic(reader, "PVMP");
  if (reader.u16() != 1 || reader.u16() != 1) {
    throw RuntimeError("unsupported package or signature format");
  }
  const auto payload_size = reader.u32();
  const auto signature_size = reader.u16();
  if (payload_size == 0 || signature_size == 0 ||
      static_cast<std::size_t>(payload_size) + signature_size != reader.remaining()) {
    throw RuntimeError("invalid package lengths");
  }
  const auto* payload = reader.bytes(payload_size);
  const auto* signature = reader.bytes(signature_size);
  verify_ed25519(payload, payload_size, signature, signature_size, public_key_path,
                 signature_verifier);
  return parse_payload(payload, payload_size, expected_application_id, expected_channel,
                       expected_platform, expected_profile, minimum_release);
}

Module load_module(const std::string& module_path, const std::string& public_key_path,
                   const std::string& expected_application_id,
                   const std::string& expected_channel,
                   const std::string& expected_platform,
                   const std::string& expected_profile, std::uint64_t minimum_release,
                   const SignatureVerifier& signature_verifier) {
  return parse_package(read_file(module_path, kMaximumModuleBytes), public_key_path,
                       expected_application_id, expected_channel, expected_platform, expected_profile,
                       minimum_release, signature_verifier);
}

void append_u16(std::vector<std::uint8_t>& output, std::uint16_t value) {
  output.push_back(static_cast<std::uint8_t>(value));
  output.push_back(static_cast<std::uint8_t>(value >> 8U));
}

void append_u64(std::vector<std::uint8_t>& output, std::uint64_t value) {
  for (unsigned shift = 0; shift < 64; shift += 8) {
    output.push_back(static_cast<std::uint8_t>(value >> shift));
  }
}

bool same_local_data(const UiNodeSnapshot& left, const UiNodeSnapshot& right) {
  if (left.properties.size() != right.properties.size() ||
      left.events.size() != right.events.size()) {
    return false;
  }
  for (std::size_t index = 0; index < left.properties.size(); ++index) {
    if (left.properties[index].key != right.properties[index].key ||
        left.properties[index].value != right.properties[index].value) {
      return false;
    }
  }
  for (std::size_t index = 0; index < left.events.size(); ++index) {
    if (left.events[index].event != right.events[index].event ||
        left.events[index].handler != right.events[index].handler) {
      return false;
    }
  }
  return true;
}

bool same_child_identity(const UiNodeSnapshot& left, const UiNodeSnapshot& right) {
  if (left.children.size() != right.children.size()) {
    return false;
  }
  for (std::size_t index = 0; index < left.children.size(); ++index) {
    if (left.children[index].type != right.children[index].type ||
        left.children[index].id != right.children[index].id) {
      return false;
    }
  }
  return true;
}

bool same_node_data(const UiNodeSnapshot& left, const UiNodeSnapshot& right) {
  if (left.type != right.type || !same_local_data(left, right) ||
      !same_child_identity(left, right)) {
    return false;
  }
  for (std::size_t index = 0; index < left.children.size(); ++index) {
    if (left.children[index].revision != right.children[index].revision) {
      return false;
    }
  }
  return true;
}

void index_snapshot(
    const UiNodeSnapshot& node,
    std::unordered_map<std::uint32_t, const UiNodeSnapshot*>& nodes_by_id) {
  nodes_by_id.emplace(node.id, &node);
  for (const auto& child : node.children) {
    index_snapshot(child, nodes_by_id);
  }
}

void assign_revisions(
    UiNodeSnapshot& node,
    const std::unordered_map<std::uint32_t, const UiNodeSnapshot*>& previous_by_id) {
  for (auto& child : node.children) {
    assign_revisions(child, previous_by_id);
  }
  const auto found = previous_by_id.find(node.id);
  if (found == previous_by_id.end() || found->second->type != node.type) {
    node.revision = 1;
    return;
  }
  const auto& previous = *found->second;
  node.local_changed = !same_local_data(previous, node);
  node.structure_changed =
      !same_child_identity(previous, node) ||
      (node.type == NodeType::NativeSurface && node.local_changed);
  node.changed = !same_node_data(previous, node);
  if (!node.changed) {
    node.revision = previous.revision;
    return;
  }
  if (previous.revision == std::numeric_limits<std::uint64_t>::max()) {
    throw RuntimeError("UI node revision exhausted");
  }
  node.revision = previous.revision + 1;
}

}  // namespace

void verify_detached_signature(const std::uint8_t* payload, std::size_t payload_size,
                               const std::uint8_t* signature, std::size_t signature_size,
                               const std::string& public_key_path,
                               SignatureVerifier signature_verifier) {
  verify_ed25519(payload, payload_size, signature, signature_size, public_key_path,
                 signature_verifier);
}

class Runtime::Impl {
 public:
  Impl(Module loaded, UiHost& ui, CapabilityHost& capability)
      : module(std::move(loaded)), state(module.initial_state), ui_host(ui), capability_host(capability) {}

  void start() {
    if (started) {
      throw RuntimeError("runtime has already started");
    }
    started = true;
    if (module.entry_handler) {
      execute(*module.entry_handler, std::nullopt);
    } else {
      render(module.entry_page);
    }
  }

  void dispatch(std::uint32_t node_id, EventType event) {
    dispatch(node_id, event, std::nullopt);
  }

  void dispatch(std::uint32_t node_id, EventType event, std::optional<std::string> value) {
    if (!started) {
      throw RuntimeError("runtime has not started");
    }
    const auto handler = find_event(module.pages[current_page], node_id, event);
    if (!handler) {
      throw RuntimeError("UI event is not registered");
    }
    if (value && value->size() > module.limits.max_state_bytes) {
      throw RuntimeError("UI event value exceeds the module memory budget");
    }
    execute(*handler, std::move(value));
  }

  void complete_effect(std::uint64_t task_id, Value result) {
    if (!started) {
      throw RuntimeError("runtime has not started");
    }
    if (!std::holds_alternative<std::string>(result)) {
      throw RuntimeError("asynchronous capability result must be a string");
    }
    if (value_size(result) > module.limits.max_state_bytes) {
      throw RuntimeError("capability result exceeds the module memory budget");
    }
    const auto found = tasks.find(task_id);
    if (found == tasks.end()) {
      throw RuntimeError("asynchronous task is missing or was cancelled");
    }
    auto frame = std::move(found->second);
    tasks.erase(found);
    frame.stack.push_back(std::move(result));
    run(std::move(frame));
  }

  void cancel_all_tasks() { tasks.clear(); }

  std::vector<std::uint8_t> snapshot_state() const {
    std::vector<std::uint8_t> output{'P', 'V', 'S', 'T'};
    const bool stable_ids = module.format >= 4;
    append_u16(output, stable_ids ? 2 : 1);
    append_u64(output, module.state_schema);
    append_u16(output, static_cast<std::uint16_t>(state.size()));
    for (std::size_t index = 0; index < state.size(); ++index) {
      const auto& value = state[index];
      if (stable_ids) {
        append_u64(output, module.state_ids[index]);
      }
      output.push_back(static_cast<std::uint8_t>(value_type(value)));
      if (const auto* integer = std::get_if<std::int64_t>(&value)) {
        std::uint64_t bits = 0;
        std::memcpy(&bits, integer, sizeof(bits));
        append_u64(output, bits);
      } else if (const auto* boolean = std::get_if<bool>(&value)) {
        output.push_back(*boolean ? 1 : 0);
      } else {
        const auto& text = std::get<std::string>(value);
        if (text.size() > std::numeric_limits<std::uint16_t>::max()) {
          throw RuntimeError("state string is too large to persist");
        }
        append_u16(output, static_cast<std::uint16_t>(text.size()));
        output.insert(output.end(), text.begin(), text.end());
      }
    }
    if (output.size() >
        module.limits.max_state_bytes + state.size() * (sizeof(std::uint64_t) + 3U) + 16U) {
      throw RuntimeError("state snapshot exceeds its resource budget");
    }
    return output;
  }

  void restore_state(const std::vector<std::uint8_t>& snapshot) {
    if (started) {
      throw RuntimeError("state can only be restored before runtime start");
    }
    Reader reader(snapshot.data(), snapshot.size());
    expect_magic(reader, "PVST");
    const auto version = reader.u16();
    const auto snapshot_schema = reader.u64();
    const auto snapshot_count = reader.u16();
    if (version == 1) {
      if (snapshot_schema != module.state_schema || snapshot_count != state.size()) {
        throw RuntimeError("state snapshot schema mismatch");
      }
      std::vector<Value> restored;
      restored.reserve(state.size());
      std::size_t state_bytes = 0;
      for (const auto& expected : state) {
        const auto type = read_value_type(reader);
        if (type != value_type(expected)) {
          throw RuntimeError("state snapshot type mismatch");
        }
        if (type == ValueType::String) {
          const auto length = reader.u16();
          const auto* bytes = reader.bytes(length);
          restored.emplace_back(std::string(reinterpret_cast<const char*>(bytes), length));
          state_bytes += length;
        } else if (type == ValueType::Integer) {
          restored.emplace_back(reader.i64());
          state_bytes += 8;
        } else {
          const auto raw = reader.u8();
          if (raw > 1) {
            throw RuntimeError("invalid persisted boolean");
          }
          restored.emplace_back(raw == 1);
          state_bytes += 1;
        }
        if (state_bytes > module.limits.max_state_bytes) {
          throw RuntimeError("persisted state exceeds its resource budget");
        }
      }
      if (!reader.empty()) {
        throw RuntimeError("unexpected trailing state data");
      }
      state = std::move(restored);
      return;
    }
    if (version != 2 || module.state_ids.size() != state.size() || snapshot_count > 4096) {
      throw RuntimeError("state snapshot schema mismatch");
    }
    std::unordered_map<std::uint64_t, Value> persisted;
    persisted.reserve(snapshot_count);
    std::size_t state_bytes = 0;
    for (std::size_t index = 0; index < snapshot_count; ++index) {
      const auto state_id = reader.u64();
      if (state_id == 0 || persisted.find(state_id) != persisted.end()) {
        throw RuntimeError("invalid or duplicate persisted state ID");
      }
      const auto type = read_value_type(reader);
      Value restored;
      if (type == ValueType::String) {
        const auto length = reader.u16();
        const auto* bytes = reader.bytes(length);
        restored = std::string(reinterpret_cast<const char*>(bytes), length);
        state_bytes += length;
      } else if (type == ValueType::Integer) {
        restored = reader.i64();
        state_bytes += 8;
      } else {
        const auto raw = reader.u8();
        if (raw > 1) {
          throw RuntimeError("invalid persisted boolean");
        }
        restored = raw == 1;
        state_bytes += 1;
      }
      if (state_bytes > module.limits.max_state_bytes) {
        throw RuntimeError("persisted state exceeds its resource budget");
      }
      persisted.emplace(state_id, std::move(restored));
    }
    if (!reader.empty()) {
      throw RuntimeError("unexpected trailing state data");
    }
    auto migrated = module.initial_state;
    std::size_t matched = 0;
    for (std::size_t index = 0; index < module.state_ids.size(); ++index) {
      const auto found = persisted.find(module.state_ids[index]);
      if (found == persisted.end()) {
        continue;
      }
      if (value_type(found->second) != value_type(migrated[index])) {
        throw RuntimeError("state snapshot type mismatch");
      }
      migrated[index] = found->second;
      ++matched;
    }
    if (snapshot_count != 0 && !module.state_ids.empty() && matched == 0) {
      throw RuntimeError("state snapshot has no compatible persistent fields");
    }
    state = std::move(migrated);
  }

  Module module;

 private:
  static std::optional<std::uint16_t> find_event(const UiNode& node, std::uint32_t node_id,
                                                  EventType event) {
    if (node.id == node_id) {
      for (const auto& binding : node.events) {
        if (binding.event == event) {
          return binding.handler;
        }
      }
    }
    for (const auto& child : node.children) {
      if (auto handler = find_event(child, node_id, event)) {
        return handler;
      }
    }
    return std::nullopt;
  }

  Value pop(std::vector<Value>& stack) {
    if (stack.empty()) {
      throw RuntimeError("runtime stack underflow");
    }
    auto result = std::move(stack.back());
    stack.pop_back();
    return result;
  }

  static std::size_t value_size(const Value& value) {
    return std::holds_alternative<std::string>(value) ? std::get<std::string>(value).size() : 8;
  }

  std::size_t state_size() const {
    std::size_t result = 0;
    for (const auto& value : state) {
      result += value_size(value);
    }
    return result;
  }

  struct Frame {
    std::uint16_t handler;
    std::size_t pc;
    std::uint32_t executed;
    std::vector<Value> stack;
    std::optional<std::string> event_value;
  };

  void execute(std::uint16_t handler_id, std::optional<std::string> event_value) {
    Frame frame{handler_id, 0, 0, {}, std::move(event_value)};
    frame.stack.reserve(std::min<std::size_t>(module.limits.max_stack, 256));
    run(std::move(frame));
  }

  void run(Frame frame) {
    const auto& code = module.handlers.at(frame.handler);
    while (true) {
      if (frame.pc >= code.size()) {
        throw RuntimeError("instruction pointer escaped handler");
      }
      if (++frame.executed > module.limits.max_instructions_per_event) {
        throw RuntimeError("instruction watchdog exceeded");
      }
      const auto& instruction = code[frame.pc];
      switch (instruction.op) {
        case Op::Constant:
          frame.stack.push_back(instruction.value);
          ++frame.pc;
          break;
        case Op::EventValue:
          if (!frame.event_value) {
            throw RuntimeError("handler requires a UI event value");
          }
          frame.stack.push_back(*frame.event_value);
          ++frame.pc;
          break;
        case Op::StateGet:
          frame.stack.push_back(state.at(instruction.first));
          ++frame.pc;
          break;
        case Op::StateSet: {
          auto value = pop(frame.stack);
          if (value_type(value) != value_type(state.at(instruction.first))) {
            throw RuntimeError("state assignment type mismatch");
          }
          const auto projected =
              state_size() - value_size(state.at(instruction.first)) + value_size(value);
          if (projected > module.limits.max_state_bytes) {
            throw RuntimeError("state mutation exceeds its resource budget");
          }
          state.at(instruction.first) = std::move(value);
          ++frame.pc;
          break;
        }
        case Op::IntegerAdd: {
          const auto right = std::get<std::int64_t>(pop(frame.stack));
          const auto left = std::get<std::int64_t>(pop(frame.stack));
          if ((right > 0 && left > std::numeric_limits<std::int64_t>::max() - right) ||
              (right < 0 && left < std::numeric_limits<std::int64_t>::min() - right)) {
            throw RuntimeError("integer overflow");
          }
          frame.stack.emplace_back(left + right);
          ++frame.pc;
          break;
        }
        case Op::Equal: {
          const auto right = pop(frame.stack);
          const auto left = pop(frame.stack);
          frame.stack.emplace_back(left == right);
          ++frame.pc;
          break;
        }
        case Op::Jump:
          frame.pc = instruction.first;
          break;
        case Op::JumpIfFalse: {
          const auto condition = std::get<bool>(pop(frame.stack));
          frame.pc = condition ? frame.pc + 1 : instruction.first;
          break;
        }
        case Op::Effect: {
          std::vector<Value> arguments;
          arguments.reserve(instruction.argument_count);
          for (std::size_t i = 0; i < instruction.argument_count; ++i) {
            arguments.push_back(pop(frame.stack));
          }
          std::reverse(arguments.begin(), arguments.end());
          auto result = capability_host.invoke(module.capabilities.at(instruction.first),
                                               module.constants.at(instruction.second), arguments);
          if (!std::holds_alternative<std::string>(result)) {
            throw RuntimeError("synchronous capability result must be a string");
          }
          if (value_size(result) > module.limits.max_state_bytes) {
            throw RuntimeError("capability result exceeds the module memory budget");
          }
          frame.stack.push_back(std::move(result));
          ++frame.pc;
          break;
        }
        case Op::AsyncEffect: {
          if (tasks.size() >= module.limits.max_tasks) {
            throw RuntimeError("asynchronous task budget exceeded");
          }
          std::vector<Value> arguments;
          arguments.reserve(instruction.argument_count);
          for (std::size_t i = 0; i < instruction.argument_count; ++i) {
            arguments.push_back(pop(frame.stack));
          }
          std::reverse(arguments.begin(), arguments.end());
          const auto task_id = next_task_id++;
          if (task_id == 0 || next_task_id == 0) {
            throw RuntimeError("asynchronous task id space exhausted");
          }
          const auto capability = module.capabilities.at(instruction.first);
          const auto operation = module.constants.at(instruction.second);
          ++frame.pc;
          tasks.emplace(task_id, std::move(frame));
          try {
            capability_host.begin_async(task_id, capability, operation, arguments);
          } catch (...) {
            tasks.erase(task_id);
            throw;
          }
          return;
        }
        case Op::Pop:
          static_cast<void>(pop(frame.stack));
          ++frame.pc;
          break;
        case Op::Render:
          render(static_cast<std::uint16_t>(instruction.first));
          ++frame.pc;
          break;
        case Op::Halt:
          return;
      }
      if (frame.stack.size() > module.limits.max_stack) {
        throw RuntimeError("runtime stack budget exceeded");
      }
    }
  }

  std::string evaluate(const PropertyExpression& expression) const {
    std::string result;
    for (const auto& segment : expression.segments) {
      result += segment.kind == 1 ? module.constants.at(segment.index)
                                  : value_to_string(state.at(segment.index));
    }
    return result;
  }

  UiNodeSnapshot snapshot(const UiNode& node) const {
    UiNodeSnapshot result{
        node.type, node.id, 0, true, true, true, {}, node.events, {}};
    result.properties.reserve(node.properties.size());
    for (const auto& property : node.properties) {
      result.properties.push_back({property.key, evaluate(property)});
    }
    result.children.reserve(node.children.size());
    for (const auto& child : node.children) {
      result.children.push_back(snapshot(child));
    }
    return result;
  }

  void render(std::uint16_t page) {
    current_page = page;
    auto next = snapshot(module.pages.at(page));
    std::unordered_map<std::uint32_t, const UiNodeSnapshot*> previous_by_id;
    if (last_snapshot) {
      previous_by_id.reserve(module.limits.max_ui_nodes);
      index_snapshot(*last_snapshot, previous_by_id);
    }
    assign_revisions(next, previous_by_id);
    if (last_snapshot && last_snapshot->type == next.type &&
        last_snapshot->id == next.id && last_snapshot->revision == next.revision) {
      return;
    }
    ui_host.replace_tree(next);
    last_snapshot = std::move(next);
  }

  std::vector<Value> state;
  UiHost& ui_host;
  CapabilityHost& capability_host;
  std::uint16_t current_page{0};
  std::optional<UiNodeSnapshot> last_snapshot;
  bool started{false};
  std::uint64_t next_task_id{1};
  std::unordered_map<std::uint64_t, Frame> tasks;
};

Runtime::Runtime(std::unique_ptr<Impl> impl) : impl_(std::move(impl)) {}
Runtime::~Runtime() = default;
Runtime::Runtime(Runtime&&) noexcept = default;
Runtime& Runtime::operator=(Runtime&&) noexcept = default;

std::unique_ptr<Runtime> Runtime::load(const std::string& module_path,
                                       const std::string& public_key_path,
                                       const std::string& expected_application_id,
                                       std::uint64_t minimum_release, UiHost& ui_host,
                                       CapabilityHost& capability_host,
                                       SignatureVerifier signature_verifier) {
  auto module = load_module(module_path, public_key_path, expected_application_id, "", "", "",
                            minimum_release, signature_verifier);
  return std::unique_ptr<Runtime>(
      new Runtime(std::make_unique<Impl>(std::move(module), ui_host, capability_host)));
}

std::unique_ptr<Runtime> Runtime::load_bound(
    const std::string& module_path, const std::string& public_key_path,
    const std::string& expected_application_id, const std::string& expected_channel,
    const std::string& expected_platform, const std::string& expected_profile,
    std::uint64_t minimum_release, UiHost& ui_host, CapabilityHost& capability_host,
    SignatureVerifier signature_verifier) {
  auto module =
      load_module(module_path, public_key_path, expected_application_id, expected_channel,
                  expected_platform, expected_profile, minimum_release, signature_verifier);
  return std::unique_ptr<Runtime>(
      new Runtime(std::make_unique<Impl>(std::move(module), ui_host, capability_host)));
}

std::unique_ptr<Runtime> Runtime::load_package(
    const std::vector<std::uint8_t>& package, const std::string& public_key_path,
    const std::string& expected_application_id, std::uint64_t minimum_release,
    UiHost& ui_host, CapabilityHost& capability_host,
    SignatureVerifier signature_verifier) {
  auto module = parse_package(package, public_key_path, expected_application_id, "", "", "",
                              minimum_release, signature_verifier);
  return std::unique_ptr<Runtime>(
      new Runtime(std::make_unique<Impl>(std::move(module), ui_host, capability_host)));
}

std::unique_ptr<Runtime> Runtime::load_package_bound(
    const std::vector<std::uint8_t>& package, const std::string& public_key_path,
    const std::string& expected_application_id, const std::string& expected_channel,
    const std::string& expected_platform, const std::string& expected_profile,
    std::uint64_t minimum_release, UiHost& ui_host, CapabilityHost& capability_host,
    SignatureVerifier signature_verifier) {
  auto module =
      parse_package(package, public_key_path, expected_application_id, expected_channel,
                    expected_platform, expected_profile, minimum_release, signature_verifier);
  return std::unique_ptr<Runtime>(
      new Runtime(std::make_unique<Impl>(std::move(module), ui_host, capability_host)));
}

void Runtime::start() { impl_->start(); }
void Runtime::dispatch(std::uint32_t node_id, EventType event) { impl_->dispatch(node_id, event); }
void Runtime::dispatch(std::uint32_t node_id, EventType event, std::string value) {
  impl_->dispatch(node_id, event, std::move(value));
}
void Runtime::complete_effect(std::uint64_t task_id, Value result) {
  impl_->complete_effect(task_id, std::move(result));
}
void Runtime::cancel_all_tasks() { impl_->cancel_all_tasks(); }
std::vector<std::uint8_t> Runtime::snapshot_state() const { return impl_->snapshot_state(); }
void Runtime::restore_state(const std::vector<std::uint8_t>& snapshot) {
  impl_->restore_state(snapshot);
}
const std::string& Runtime::application_id() const { return impl_->module.application_id; }
const std::string& Runtime::channel() const { return impl_->module.channel; }
std::uint64_t Runtime::release() const { return impl_->module.release; }
const std::vector<std::string>& Runtime::capabilities() const {
  return impl_->module.capabilities;
}
const std::vector<std::uint16_t>& Runtime::capability_versions() const {
  return impl_->module.capability_versions;
}
const std::vector<std::string>& Runtime::network_domains() const {
  return impl_->module.domains;
}
const std::vector<std::string>& Runtime::storage_scopes() const {
  return impl_->module.storage_scopes;
}
std::string Runtime::delivery_profile() const {
  static constexpr std::array<const char*, 4> names{
      "offline_sealed",
      "online_provisioned",
      "store_on_demand",
      "enterprise_managed",
  };
  return names.at(impl_->module.profile - 1);
}
std::string Runtime::target_platform() const {
  static constexpr std::array<const char*, 4> names{
      "android",
      "ios",
      "harmonyos",
      "desktop",
  };
  return names.at(impl_->module.platform - 1);
}

const char* node_type_name(NodeType type) {
  static constexpr std::array<const char*, 11> names{
      "Text",   "Image", "Row",    "Column", "Stack",  "Scroll",
      "List",   "Button", "Input", "Switch", "NativeSurface",
  };
  return names.at(static_cast<std::size_t>(type) - 1);
}

const char* property_key_name(PropertyKey key) {
  static constexpr std::array<const char*, 6> names{
      "text", "source", "accessibilityLabel", "enabled", "value", "surfaceType",
  };
  return names.at(static_cast<std::size_t>(key) - 1);
}

const char* event_type_name(EventType type) {
  static constexpr std::array<const char*, 4> names{"tap", "change", "submit", "appear"};
  return names.at(static_cast<std::size_t>(type) - 1);
}

std::string value_to_string(const Value& value) {
  if (const auto* integer = std::get_if<std::int64_t>(&value)) {
    return std::to_string(*integer);
  }
  if (const auto* boolean = std::get_if<bool>(&value)) {
    return *boolean ? "true" : "false";
  }
  return std::get<std::string>(value);
}

}  // namespace pvm
