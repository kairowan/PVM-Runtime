#include "pvm/runtime_c.h"

#include "pvm/runtime.hpp"

#include <algorithm>
#include <cstring>
#include <memory>
#include <sstream>
#include <string>
#include <vector>

namespace {

std::string json_escape(const std::string& value) {
  std::ostringstream output;
  for (const unsigned char byte : value) {
    switch (byte) {
      case '"':
        output << "\\\"";
        break;
      case '\\':
        output << "\\\\";
        break;
      case '\b':
        output << "\\b";
        break;
      case '\f':
        output << "\\f";
        break;
      case '\n':
        output << "\\n";
        break;
      case '\r':
        output << "\\r";
        break;
      case '\t':
        output << "\\t";
        break;
      default:
        if (byte < 0x20) {
          static constexpr char hex[] = "0123456789abcdef";
          output << "\\u00" << hex[byte >> 4U] << hex[byte & 0x0FU];
        } else {
          output << static_cast<char>(byte);
        }
    }
  }
  return output.str();
}

void write_value(std::ostringstream& output, const pvm::Value& value) {
  if (const auto* integer = std::get_if<std::int64_t>(&value)) {
    output << *integer;
  } else if (const auto* boolean = std::get_if<bool>(&value)) {
    output << (*boolean ? "true" : "false");
  } else {
    output << '"' << json_escape(std::get<std::string>(value)) << '"';
  }
}

void write_node(std::ostringstream& output, const pvm::UiNodeSnapshot& node) {
  output << "{\"type\":\"" << pvm::node_type_name(node.type) << "\",\"id\":" << node.id
         << ",\"props\":{";
  for (std::size_t i = 0; i < node.properties.size(); ++i) {
    if (i != 0) {
      output << ',';
    }
    output << '"' << pvm::property_key_name(node.properties[i].key) << "\":\""
           << json_escape(node.properties[i].value) << '"';
  }
  output << "},\"events\":[";
  for (std::size_t i = 0; i < node.events.size(); ++i) {
    if (i != 0) {
      output << ',';
    }
    output << '"' << pvm::event_type_name(node.events[i].event) << '"';
  }
  output << "],\"children\":[";
  for (std::size_t i = 0; i < node.children.size(); ++i) {
    if (i != 0) {
      output << ',';
    }
    write_node(output, node.children[i]);
  }
  output << "]}";
}

class CallbackHost final : public pvm::UiHost, public pvm::CapabilityHost {
 public:
  explicit CallbackHost(pvm_host_callbacks_v2 supplied) : callbacks_(supplied) {}

  void replace_tree(const pvm::UiNodeSnapshot& root) override {
    if (callbacks_.on_ui_batch == nullptr) {
      throw pvm::RuntimeError("UI host callback is not installed");
    }
    std::ostringstream output;
    output << "{\"operation\":\"replace\",\"root\":";
    write_node(output, root);
    output << '}';
    const auto json = output.str();
    callbacks_.on_ui_batch(callbacks_.context, json.data(), json.size());
  }

  pvm::Value invoke(const std::string& capability, const std::string& operation,
                    const std::vector<pvm::Value>& arguments) override {
    if (callbacks_.on_effect == nullptr) {
      throw pvm::RuntimeError("capability host callback is not installed");
    }
    std::ostringstream output;
    output << '[';
    for (std::size_t i = 0; i < arguments.size(); ++i) {
      if (i != 0) {
        output << ',';
      }
      write_value(output, arguments[i]);
    }
    output << ']';
    const auto arguments_json = output.str();
    const char* result = callbacks_.on_effect(callbacks_.context, capability.c_str(),
                                              operation.c_str(), arguments_json.c_str());
    if (result == nullptr) {
      throw pvm::RuntimeError("capability host rejected the effect");
    }
    return std::string(result);
  }

  void begin_async(std::uint64_t task_id, const std::string& capability,
                   const std::string& operation,
                   const std::vector<pvm::Value>& arguments) override {
    if (callbacks_.on_async_effect == nullptr) {
      throw pvm::RuntimeError("asynchronous capability host callback is not installed");
    }
    std::ostringstream output;
    output << '[';
    for (std::size_t i = 0; i < arguments.size(); ++i) {
      if (i != 0) {
        output << ',';
      }
      write_value(output, arguments[i]);
    }
    output << ']';
    const auto arguments_json = output.str();
    callbacks_.on_async_effect(callbacks_.context, task_id, capability.c_str(), operation.c_str(),
                               arguments_json.c_str());
  }

 private:
  pvm_host_callbacks_v2 callbacks_;
};

void set_error(char* output, std::size_t capacity, const std::string& message) {
  if (output == nullptr || capacity == 0) {
    return;
  }
  const auto length = std::min(capacity - 1, message.size());
  std::memcpy(output, message.data(), length);
  output[length] = '\0';
}

template <typename Function>
int guard(char* error, std::size_t error_capacity, Function function) {
  try {
    function();
    set_error(error, error_capacity, "");
    return 1;
  } catch (const std::exception& exception) {
    set_error(error, error_capacity, exception.what());
    return 0;
  } catch (...) {
    set_error(error, error_capacity, "unknown runtime error");
    return 0;
  }
}

}  // namespace

struct pvm_runtime {
  std::unique_ptr<CallbackHost> host;
  std::unique_ptr<pvm::Runtime> runtime;
};

pvm_runtime* pvm_runtime_create(const char* module_path, const char* public_key_path,
                                const char* expected_application_id, std::uint64_t minimum_release,
                                pvm_host_callbacks callbacks, char* error,
                                std::size_t error_capacity) {
  const pvm_host_callbacks_v2 upgraded{
      callbacks.context,
      callbacks.on_ui_batch,
      callbacks.on_effect,
      callbacks.on_async_effect,
      nullptr,
  };
  return pvm_runtime_create_v2(module_path, public_key_path, expected_application_id,
                               minimum_release, upgraded, error, error_capacity);
}

pvm_runtime* pvm_runtime_create_v2(
    const char* module_path, const char* public_key_path, const char* expected_application_id,
    std::uint64_t minimum_release, pvm_host_callbacks_v2 callbacks, char* error,
    std::size_t error_capacity) {
  try {
    if (module_path == nullptr || public_key_path == nullptr || expected_application_id == nullptr) {
      throw pvm::RuntimeError("runtime create arguments must not be null");
    }
    auto handle = std::make_unique<pvm_runtime>();
    handle->host = std::make_unique<CallbackHost>(callbacks);
    pvm::SignatureVerifier verifier;
    if (callbacks.on_verify_signature != nullptr) {
      verifier = [callbacks](const std::uint8_t* payload, std::size_t payload_size,
                             const std::uint8_t* signature, std::size_t signature_size,
                             const std::string& public_key_path) {
        return callbacks.on_verify_signature(callbacks.context, payload, payload_size, signature,
                                             signature_size, public_key_path.c_str()) == 1;
      };
    }
    handle->runtime =
        pvm::Runtime::load(module_path, public_key_path, expected_application_id, minimum_release,
                           *handle->host, *handle->host, std::move(verifier));
    set_error(error, error_capacity, "");
    return handle.release();
  } catch (const std::exception& exception) {
    set_error(error, error_capacity, exception.what());
    return nullptr;
  } catch (...) {
    set_error(error, error_capacity, "unknown runtime error");
    return nullptr;
  }
}

int pvm_runtime_start(pvm_runtime* runtime, char* error, std::size_t error_capacity) {
  return guard(error, error_capacity, [&] {
    if (runtime == nullptr) {
      throw pvm::RuntimeError("runtime is null");
    }
    runtime->runtime->start();
  });
}

int pvm_runtime_dispatch(pvm_runtime* runtime, std::uint32_t node_id, std::uint8_t event_type,
                         char* error, std::size_t error_capacity) {
  return guard(error, error_capacity, [&] {
    if (runtime == nullptr || event_type < 1 || event_type > 4) {
      throw pvm::RuntimeError("invalid dispatch arguments");
    }
    runtime->runtime->dispatch(node_id, static_cast<pvm::EventType>(event_type));
  });
}

int pvm_runtime_dispatch_value(pvm_runtime* runtime, std::uint32_t node_id,
                               std::uint8_t event_type, const char* value, char* error,
                               std::size_t error_capacity) {
  return guard(error, error_capacity, [&] {
    if (runtime == nullptr || value == nullptr || event_type < 1 || event_type > 4) {
      throw pvm::RuntimeError("invalid dispatch arguments");
    }
    runtime->runtime->dispatch(node_id, static_cast<pvm::EventType>(event_type),
                               std::string(value));
  });
}

int pvm_runtime_complete_effect(pvm_runtime* runtime, std::uint64_t task_id, const char* result,
                                char* error, std::size_t error_capacity) {
  return guard(error, error_capacity, [&] {
    if (runtime == nullptr || task_id == 0 || result == nullptr) {
      throw pvm::RuntimeError("invalid asynchronous completion arguments");
    }
    runtime->runtime->complete_effect(task_id, std::string(result));
  });
}

void pvm_runtime_cancel_all_tasks(pvm_runtime* runtime) {
  if (runtime != nullptr) {
    runtime->runtime->cancel_all_tasks();
  }
}

std::size_t pvm_runtime_snapshot_state(pvm_runtime* runtime, std::uint8_t* output,
                                       std::size_t output_capacity, char* error,
                                       std::size_t error_capacity) {
  std::size_t result = 0;
  const auto ok = guard(error, error_capacity, [&] {
    if (runtime == nullptr) {
      throw pvm::RuntimeError("runtime is null");
    }
    const auto snapshot = runtime->runtime->snapshot_state();
    result = snapshot.size();
    if (output != nullptr) {
      if (output_capacity < snapshot.size()) {
        throw pvm::RuntimeError("state output buffer is too small");
      }
      std::copy(snapshot.begin(), snapshot.end(), output);
    }
  });
  return ok ? result : 0;
}

int pvm_runtime_restore_state(pvm_runtime* runtime, const std::uint8_t* input,
                              std::size_t input_size, char* error, std::size_t error_capacity) {
  return guard(error, error_capacity, [&] {
    if (runtime == nullptr || input == nullptr || input_size == 0) {
      throw pvm::RuntimeError("invalid restore arguments");
    }
    runtime->runtime->restore_state(std::vector<std::uint8_t>(input, input + input_size));
  });
}

std::size_t pvm_runtime_metadata_json(pvm_runtime* runtime, char* output,
                                      std::size_t output_capacity, char* error,
                                      std::size_t error_capacity) {
  std::size_t result = 0;
  const auto ok = guard(error, error_capacity, [&] {
    if (runtime == nullptr) {
      throw pvm::RuntimeError("runtime is null");
    }
    std::ostringstream json;
    json << "{\"applicationId\":\"" << json_escape(runtime->runtime->application_id())
         << "\",\"release\":" << runtime->runtime->release()
         << ",\"profile\":\"" << json_escape(runtime->runtime->delivery_profile())
         << "\",\"platform\":\"" << json_escape(runtime->runtime->target_platform()) << '"';
    const auto write_table = [&](const char* name, const std::vector<std::string>& values) {
      json << ",\"" << name << "\":[";
      for (std::size_t i = 0; i < values.size(); ++i) {
        if (i != 0) {
          json << ',';
        }
        json << '"' << json_escape(values[i]) << '"';
      }
      json << ']';
    };
    write_table("capabilities", runtime->runtime->capabilities());
    json << ",\"capabilityVersions\":{";
    const auto& capabilities = runtime->runtime->capabilities();
    const auto& versions = runtime->runtime->capability_versions();
    for (std::size_t i = 0; i < capabilities.size(); ++i) {
      if (i != 0) {
        json << ',';
      }
      json << '"' << json_escape(capabilities[i]) << "\":" << versions[i];
    }
    json << '}';
    write_table("networkDomains", runtime->runtime->network_domains());
    write_table("storageScopes", runtime->runtime->storage_scopes());
    json << '}';
    const auto encoded = json.str();
    result = encoded.size();
    if (output != nullptr) {
      if (output_capacity < encoded.size()) {
        throw pvm::RuntimeError("metadata output buffer is too small");
      }
      std::copy(encoded.begin(), encoded.end(), output);
    }
  });
  return ok ? result : 0;
}

std::uint64_t pvm_runtime_release(const pvm_runtime* runtime) {
  return runtime == nullptr ? 0 : runtime->runtime->release();
}

void pvm_runtime_destroy(pvm_runtime* runtime) { delete runtime; }
