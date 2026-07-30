#include "pvm/runtime.hpp"

#include <filesystem>
#include <fstream>
#include <iostream>
#include <optional>
#include <string>
#include <vector>

namespace {

struct Options {
  std::string module;
  std::string public_key;
  std::string application_id;
  std::string expected_channel{"enterprise"};
  std::string expected_platform{"desktop"};
  std::string expected_profile;
  std::string state_file;
  std::string verify_payload;
  std::string verify_signature;
  std::uint64_t minimum_release{0};
  std::optional<std::size_t> tap_index;
  bool validate_only{false};
};

void usage(const char* program) {
  std::cerr << "Usage: " << program
            << " --module FILE --public-key FILE --app-id ID [--min-release N]"
               " [--channel CHANNEL] [--platform PLATFORM] [--profile PROFILE]"
               " [--state-file FILE] [--tap-index N] [--validate-only]\n"
            << "       " << program
            << " --verify-payload FILE --verify-signature FILE --public-key FILE\n";
}

Options parse_options(int argc, char** argv) {
  Options options;
  for (int i = 1; i < argc; ++i) {
    const std::string argument = argv[i];
    auto value = [&]() -> std::string {
      if (++i >= argc) {
        throw pvm::RuntimeError("missing value after " + argument);
      }
      return argv[i];
    };
    if (argument == "--module") {
      options.module = value();
    } else if (argument == "--public-key") {
      options.public_key = value();
    } else if (argument == "--app-id") {
      options.application_id = value();
    } else if (argument == "--min-release") {
      options.minimum_release = std::stoull(value());
    } else if (argument == "--platform") {
      options.expected_platform = value();
    } else if (argument == "--channel") {
      options.expected_channel = value();
    } else if (argument == "--profile") {
      options.expected_profile = value();
    } else if (argument == "--state-file") {
      options.state_file = value();
    } else if (argument == "--verify-payload") {
      options.verify_payload = value();
    } else if (argument == "--verify-signature") {
      options.verify_signature = value();
    } else if (argument == "--tap-index") {
      options.tap_index = std::stoull(value());
    } else if (argument == "--validate-only") {
      options.validate_only = true;
    } else if (argument == "--help") {
      usage(argv[0]);
      std::exit(0);
    } else {
      throw pvm::RuntimeError("unknown argument: " + argument);
    }
  }
  if (options.public_key.empty()) {
    throw pvm::RuntimeError("--public-key is required");
  }
  const bool detached = !options.verify_payload.empty() || !options.verify_signature.empty();
  if (detached && (options.verify_payload.empty() || options.verify_signature.empty())) {
    throw pvm::RuntimeError("--verify-payload and --verify-signature must be used together");
  }
  if (!detached && (options.module.empty() || options.application_id.empty())) {
    throw pvm::RuntimeError("--module, --public-key, and --app-id are required");
  }
  return options;
}

class ConsoleHost final : public pvm::UiHost, public pvm::CapabilityHost {
 public:
  void replace_tree(const pvm::UiNodeSnapshot& root) override {
    tap_nodes.clear();
    std::cout << "UI batch: replace\n";
    print(root, 0);
  }

  pvm::Value invoke(const std::string& capability, const std::string& operation,
                    const std::vector<pvm::Value>& arguments) override {
    std::cout << "Effect: " << capability << '.' << operation << '(';
    for (std::size_t i = 0; i < arguments.size(); ++i) {
      if (i != 0) {
        std::cout << ", ";
      }
      std::cout << pvm::value_to_string(arguments[i]);
    }
    std::cout << ")\n";
    return std::string("ok");
  }

  void begin_async(std::uint64_t, const std::string&, const std::string&,
                   const std::vector<pvm::Value>&) override {
    throw pvm::RuntimeError("console host does not install asynchronous capabilities");
  }

  std::vector<std::uint32_t> tap_nodes;

 private:
  void print(const pvm::UiNodeSnapshot& node, std::size_t depth) {
    std::cout << std::string(depth * 2, ' ') << pvm::node_type_name(node.type) << '#'
              << node.id;
    for (const auto& property : node.properties) {
      std::cout << ' ' << pvm::property_key_name(property.key) << "=\"" << property.value << '"';
    }
    for (const auto& event : node.events) {
      std::cout << " [" << pvm::event_type_name(event.event) << ']';
      if (event.event == pvm::EventType::Tap) {
        tap_nodes.push_back(node.id);
      }
    }
    std::cout << '\n';
    for (const auto& child : node.children) {
      print(child, depth + 1);
    }
  }
};

std::vector<std::uint8_t> read_state(const std::string& path) {
  std::ifstream input(path, std::ios::binary | std::ios::ate);
  if (!input) {
    return {};
  }
  const auto size = input.tellg();
  if (size < 0 || size > 1024 * 1024) {
    throw pvm::RuntimeError("state file is invalid or too large");
  }
  std::vector<std::uint8_t> bytes(static_cast<std::size_t>(size));
  input.seekg(0);
  if (!bytes.empty() &&
      !input.read(reinterpret_cast<char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()))) {
    throw pvm::RuntimeError("cannot read state file");
  }
  return bytes;
}

void write_state(const std::string& path, const std::vector<std::uint8_t>& state) {
  const auto temporary = path + ".tmp";
  {
    std::ofstream output(temporary, std::ios::binary | std::ios::trunc);
    if (!output ||
        !output.write(reinterpret_cast<const char*>(state.data()),
                      static_cast<std::streamsize>(state.size()))) {
      throw pvm::RuntimeError("cannot write state file");
    }
  }
  std::error_code error;
  std::filesystem::rename(temporary, path, error);
  if (error) {
    std::filesystem::remove(path, error);
    error.clear();
    std::filesystem::rename(temporary, path, error);
  }
  if (error) {
    throw pvm::RuntimeError("cannot atomically replace state file: " + error.message());
  }
}

}  // namespace

int main(int argc, char** argv) {
  try {
    const auto options = parse_options(argc, argv);
    if (!options.verify_payload.empty()) {
      const auto payload = read_state(options.verify_payload);
      const auto signature = read_state(options.verify_signature);
      if (payload.empty()) {
        throw pvm::RuntimeError("signed payload is empty");
      }
      pvm::verify_detached_signature(payload.data(), payload.size(), signature.data(),
                                     signature.size(), options.public_key);
      std::cout << "Validated detached signature\n";
      return 0;
    }
    ConsoleHost host;
    auto runtime = pvm::Runtime::load_bound(
        options.module, options.public_key, options.application_id, options.expected_channel,
        options.expected_platform, options.expected_profile, options.minimum_release, host, host);
    std::cout << "Validated " << runtime->application_id() << " release " << runtime->release()
              << '\n';
    if (options.validate_only) {
      return 0;
    }
    if (!options.state_file.empty()) {
      const auto persisted = read_state(options.state_file);
      if (!persisted.empty()) {
        runtime->restore_state(persisted);
        std::cout << "Restored persisted state\n";
      }
    }
    runtime->start();
    if (options.tap_index) {
      if (*options.tap_index >= host.tap_nodes.size()) {
        throw pvm::RuntimeError("--tap-index does not identify a rendered tap target");
      }
      const auto node = host.tap_nodes[*options.tap_index];
      runtime->dispatch(node, pvm::EventType::Tap);
    }
    if (!options.state_file.empty()) {
      write_state(options.state_file, runtime->snapshot_state());
      std::cout << "Persisted state\n";
    }
    return 0;
  } catch (const std::exception& exception) {
    std::cerr << "error: " << exception.what() << '\n';
    usage(argv[0]);
    return 1;
  }
}
