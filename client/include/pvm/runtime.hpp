#pragma once

#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>
#include <stdexcept>
#include <string>
#include <variant>
#include <vector>

namespace pvm {

constexpr std::uint16_t kRuntimeVersion = 5;

enum class ValueType : std::uint8_t { Integer = 1, Boolean = 2, String = 3 };
using Value = std::variant<std::int64_t, bool, std::string>;
using SignatureVerifier =
    std::function<bool(const std::uint8_t* payload, std::size_t payload_size,
                       const std::uint8_t* signature, std::size_t signature_size,
                       const std::string& public_key_path)>;

void verify_detached_signature(const std::uint8_t* payload, std::size_t payload_size,
                               const std::uint8_t* signature, std::size_t signature_size,
                               const std::string& public_key_path,
                               SignatureVerifier signature_verifier = {});

enum class NodeType : std::uint8_t {
  Text = 1,
  Image = 2,
  Row = 3,
  Column = 4,
  Stack = 5,
  Scroll = 6,
  List = 7,
  Button = 8,
  Input = 9,
  Switch = 10,
  NativeSurface = 11,
};

enum class PropertyKey : std::uint8_t {
  Text = 1,
  Source = 2,
  AccessibilityLabel = 3,
  Enabled = 4,
  Value = 5,
  SurfaceType = 6,
};

enum class EventType : std::uint8_t { Tap = 1, Change = 2, Submit = 3, Appear = 4 };

struct Property {
  PropertyKey key;
  std::string value;
};

struct EventBinding {
  EventType event;
  std::uint16_t handler;
};

struct UiNodeSnapshot {
  NodeType type;
  std::uint32_t id;
  std::vector<Property> properties;
  std::vector<EventBinding> events;
  std::vector<UiNodeSnapshot> children;
};

class UiHost {
 public:
  virtual ~UiHost() = default;
  virtual void replace_tree(const UiNodeSnapshot& root) = 0;
};

class CapabilityHost {
 public:
  virtual ~CapabilityHost() = default;
  virtual Value invoke(const std::string& capability, const std::string& operation,
                       const std::vector<Value>& arguments) = 0;
  virtual void begin_async(std::uint64_t task_id, const std::string& capability,
                           const std::string& operation,
                           const std::vector<Value>& arguments) = 0;
};

class RuntimeError : public std::runtime_error {
 public:
  using std::runtime_error::runtime_error;
};

class Runtime {
 public:
  static std::unique_ptr<Runtime> load(const std::string& module_path,
                                       const std::string& public_key_path,
                                       const std::string& expected_application_id,
                                       std::uint64_t minimum_release, UiHost& ui_host,
                                       CapabilityHost& capability_host,
                                       SignatureVerifier signature_verifier = {});
  static std::unique_ptr<Runtime> load_package(
      const std::vector<std::uint8_t>& package, const std::string& public_key_path,
      const std::string& expected_application_id, std::uint64_t minimum_release,
      UiHost& ui_host, CapabilityHost& capability_host,
      SignatureVerifier signature_verifier = {});
  ~Runtime();
  Runtime(Runtime&&) noexcept;
  Runtime& operator=(Runtime&&) noexcept;
  Runtime(const Runtime&) = delete;
  Runtime& operator=(const Runtime&) = delete;

  void start();
  void dispatch(std::uint32_t node_id, EventType event);
  void dispatch(std::uint32_t node_id, EventType event, std::string value);
  void complete_effect(std::uint64_t task_id, Value result);
  void cancel_all_tasks();
  std::vector<std::uint8_t> snapshot_state() const;
  void restore_state(const std::vector<std::uint8_t>& snapshot);

  const std::string& application_id() const;
  std::uint64_t release() const;
  const std::vector<std::string>& capabilities() const;
  const std::vector<std::uint16_t>& capability_versions() const;
  const std::vector<std::string>& network_domains() const;
  const std::vector<std::string>& storage_scopes() const;
  std::string delivery_profile() const;
  std::string target_platform() const;

 private:
  class Impl;
  explicit Runtime(std::unique_ptr<Impl> impl);
  std::unique_ptr<Impl> impl_;
};

const char* node_type_name(NodeType type);
const char* property_key_name(PropertyKey key);
const char* event_type_name(EventType type);
std::string value_to_string(const Value& value);

}  // namespace pvm
