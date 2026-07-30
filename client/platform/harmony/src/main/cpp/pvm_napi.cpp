#define NAPI_VERSION 8
#include <node_api.h>

#include "pvm/runtime_c.h"

#include <cmath>
#include <cstdint>
#include <cstring>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

constexpr double kMaximumSafeInteger = 9'007'199'254'740'991.0;

bool is_safe_integer(double value) {
  return std::isfinite(value) && std::floor(value) == value &&
         std::abs(value) <= kMaximumSafeInteger;
}

struct Bridge {
  napi_env env{nullptr};
  napi_ref ui{nullptr};
  napi_ref sync_effect{nullptr};
  napi_ref async_effect{nullptr};
  napi_ref verify_signature{nullptr};
  pvm_runtime* runtime{nullptr};
  std::string sync_result;

  void close() {
    if (runtime != nullptr) {
      pvm_runtime_destroy(runtime);
      runtime = nullptr;
    }
    if (ui != nullptr) napi_delete_reference(env, ui);
    if (sync_effect != nullptr) napi_delete_reference(env, sync_effect);
    if (async_effect != nullptr) napi_delete_reference(env, async_effect);
    if (verify_signature != nullptr) napi_delete_reference(env, verify_signature);
    ui = nullptr;
    sync_effect = nullptr;
    async_effect = nullptr;
    verify_signature = nullptr;
  }

  ~Bridge() { close(); }
};

void check(napi_status status, const char* operation) {
  if (status != napi_ok) throw std::runtime_error(operation);
}

std::string string_value(napi_env env, napi_value value) {
  std::size_t size = 0;
  check(napi_get_value_string_utf8(env, value, nullptr, 0, &size), "Expected UTF-8 string");
  std::string result(size, '\0');
  check(napi_get_value_string_utf8(env, value, result.data(), size + 1, &size),
        "Cannot read UTF-8 string");
  return result;
}

napi_value string_value(napi_env env, const char* value, std::size_t size) {
  napi_value result = nullptr;
  check(napi_create_string_utf8(env, value, size, &result), "Cannot create UTF-8 string");
  return result;
}

napi_value string_value(napi_env env, const char* value) {
  return string_value(env, value, NAPI_AUTO_LENGTH);
}

napi_value call(napi_env env, napi_ref callback, std::size_t argc, napi_value* argv) {
  napi_value function = nullptr;
  napi_value global = nullptr;
  napi_value result = nullptr;
  check(napi_get_reference_value(env, callback, &function), "Missing host callback");
  check(napi_get_global(env, &global), "Cannot access global object");
  check(napi_call_function(env, global, function, argc, argv, &result), "Host callback failed");
  return result;
}

void ui_callback(void* context, const char* json, std::size_t size) {
  auto& bridge = *static_cast<Bridge*>(context);
  napi_value argument = string_value(bridge.env, json, size);
  static_cast<void>(call(bridge.env, bridge.ui, 1, &argument));
}

const char* sync_effect_callback(void* context, const char* capability, const char* operation,
                                 const char* arguments_json) {
  auto& bridge = *static_cast<Bridge*>(context);
  napi_value arguments[]{
      string_value(bridge.env, capability),
      string_value(bridge.env, operation),
      string_value(bridge.env, arguments_json),
  };
  const auto result = call(bridge.env, bridge.sync_effect, 3, arguments);
  napi_valuetype type = napi_undefined;
  check(napi_typeof(bridge.env, result, &type), "Cannot inspect capability result");
  if (type != napi_string) return nullptr;
  bridge.sync_result = string_value(bridge.env, result);
  return bridge.sync_result.c_str();
}

void async_effect_callback(void* context, std::uint64_t task_id, const char* capability,
                           const char* operation, const char* arguments_json) {
  auto& bridge = *static_cast<Bridge*>(context);
  const auto task = std::to_string(task_id);
  napi_value arguments[]{
      string_value(bridge.env, task.c_str(), task.size()),
      string_value(bridge.env, capability),
      string_value(bridge.env, operation),
      string_value(bridge.env, arguments_json),
  };
  static_cast<void>(call(bridge.env, bridge.async_effect, 4, arguments));
}

int signature_verify_callback(void* context, const std::uint8_t* payload,
                              std::size_t payload_size, const std::uint8_t* signature,
                              std::size_t signature_size, const char* public_key_path) {
  auto& bridge = *static_cast<Bridge*>(context);
  napi_value payload_buffer = nullptr;
  napi_value signature_buffer = nullptr;
  void* payload_output = nullptr;
  void* signature_output = nullptr;
  check(napi_create_arraybuffer(bridge.env, payload_size, &payload_output, &payload_buffer),
        "Cannot allocate signature payload");
  check(napi_create_arraybuffer(
            bridge.env, signature_size, &signature_output, &signature_buffer),
        "Cannot allocate module signature");
  std::memcpy(payload_output, payload, payload_size);
  std::memcpy(signature_output, signature, signature_size);
  napi_value arguments[]{
      payload_buffer,
      signature_buffer,
      string_value(bridge.env, public_key_path),
  };
  const auto result = call(bridge.env, bridge.verify_signature, 3, arguments);
  bool verified = false;
  check(napi_get_value_bool(bridge.env, result, &verified),
        "Signature verifier must return boolean");
  return verified ? 1 : 0;
}

void release_bridge(napi_env, Bridge* bridge) { delete bridge; }

void finalize(napi_env env, void* data, void*) { release_bridge(env, static_cast<Bridge*>(data)); }

Bridge* bridge_value(napi_env env, napi_value value) {
  void* raw = nullptr;
  check(napi_get_value_external(env, value, &raw), "Expected runtime handle");
  auto* bridge = static_cast<Bridge*>(raw);
  if (bridge == nullptr || bridge->runtime == nullptr) throw std::runtime_error("Runtime is closed");
  return bridge;
}

std::vector<napi_value> arguments(napi_env env, napi_callback_info info, std::size_t expected) {
  std::vector<napi_value> result(expected);
  std::size_t count = expected;
  check(napi_get_cb_info(env, info, &count, result.data(), nullptr, nullptr),
        "Cannot read arguments");
  if (count != expected) throw std::runtime_error("Invalid argument count");
  return result;
}

napi_ref callback_property(napi_env env, napi_value object, const char* name) {
  napi_value value = nullptr;
  check(napi_get_named_property(env, object, name, &value), "Missing callback property");
  napi_valuetype type = napi_undefined;
  check(napi_typeof(env, value, &type), "Cannot inspect callback");
  if (type != napi_function) throw std::runtime_error(std::string(name) + " must be a function");
  napi_ref result = nullptr;
  check(napi_create_reference(env, value, 1, &result), "Cannot retain callback");
  return result;
}

napi_value create(napi_env env, napi_callback_info info) {
  try {
    const auto argv = arguments(env, info, 7);
    auto bridge = std::make_unique<Bridge>();
    bridge->env = env;
    bridge->ui = callback_property(env, argv[6], "onUi");
    bridge->sync_effect = callback_property(env, argv[6], "onSyncEffect");
    bridge->async_effect = callback_property(env, argv[6], "onAsyncEffect");
    bridge->verify_signature = callback_property(env, argv[6], "onVerifySignature");
    double minimum_release = 0;
    check(napi_get_value_double(env, argv[3], &minimum_release), "minimumRelease must be a number");
    if (!is_safe_integer(minimum_release) || minimum_release < 0) {
      throw std::runtime_error("minimumRelease must be a non-negative safe integer");
    }
    const auto module = string_value(env, argv[0]);
    const auto key = string_value(env, argv[1]);
    const auto app = string_value(env, argv[2]);
    const auto channel = string_value(env, argv[4]);
    const auto profile = string_value(env, argv[5]);
    char error[512]{};
    const pvm_host_callbacks_v2 callbacks{
        bridge.get(), ui_callback, sync_effect_callback, async_effect_callback,
        signature_verify_callback};
    bridge->runtime =
        pvm_runtime_create_v3(
            module.c_str(), key.c_str(), app.c_str(), channel.c_str(), "harmonyos",
            profile.c_str(), static_cast<std::uint64_t>(minimum_release), callbacks, error,
            sizeof(error));
    if (bridge->runtime == nullptr) throw std::runtime_error(error);
    napi_value result = nullptr;
    check(napi_create_external(env, bridge.get(), finalize, nullptr, &result),
          "Cannot create runtime handle");
    bridge.release();
    return result;
  } catch (const std::exception& error) {
    napi_throw_error(env, nullptr, error.what());
    return nullptr;
  }
}

template <typename Function>
napi_value guarded(napi_env env, napi_callback_info info, std::size_t argc, Function function) {
  try {
    const auto argv = arguments(env, info, argc);
    return function(argv);
  } catch (const std::exception& error) {
    napi_throw_error(env, nullptr, error.what());
    return nullptr;
  }
}

napi_value undefined(napi_env env) {
  napi_value result = nullptr;
  check(napi_get_undefined(env, &result), "Cannot create undefined");
  return result;
}

napi_value start(napi_env env, napi_callback_info info) {
  return guarded(env, info, 1, [&](const auto& argv) {
    auto* bridge = bridge_value(env, argv[0]);
    char error[512]{};
    if (!pvm_runtime_start(bridge->runtime, error, sizeof(error))) throw std::runtime_error(error);
    return undefined(env);
  });
}

napi_value dispatch(napi_env env, napi_callback_info info) {
  return guarded(env, info, 3, [&](const auto& argv) {
    auto* bridge = bridge_value(env, argv[0]);
    double node = 0;
    double event = 0;
    check(napi_get_value_double(env, argv[1], &node), "nodeId must be a number");
    check(napi_get_value_double(env, argv[2], &event), "event must be a number");
    if (!is_safe_integer(node) || node <= 0 || node > UINT32_MAX) {
      throw std::runtime_error("Invalid node id");
    }
    if (!is_safe_integer(event) || event < 1 || event > 4) {
      throw std::runtime_error("Invalid event");
    }
    char error[512]{};
    if (!pvm_runtime_dispatch(bridge->runtime, static_cast<std::uint32_t>(node),
                              static_cast<std::uint8_t>(event), error, sizeof(error))) {
      throw std::runtime_error(error);
    }
    return undefined(env);
  });
}

napi_value dispatch_value(napi_env env, napi_callback_info info) {
  return guarded(env, info, 4, [&](const auto& argv) {
    auto* bridge = bridge_value(env, argv[0]);
    double node = 0;
    double event = 0;
    check(napi_get_value_double(env, argv[1], &node), "nodeId must be a number");
    check(napi_get_value_double(env, argv[2], &event), "event must be a number");
    const auto value = string_value(env, argv[3]);
    if (!is_safe_integer(node) || node <= 0 || node > UINT32_MAX) {
      throw std::runtime_error("Invalid node id");
    }
    if (!is_safe_integer(event) || event < 1 || event > 4) {
      throw std::runtime_error("Invalid event");
    }
    char error[512]{};
    if (!pvm_runtime_dispatch_value(bridge->runtime, static_cast<std::uint32_t>(node),
                                    static_cast<std::uint8_t>(event), value.c_str(), error,
                                    sizeof(error))) {
      throw std::runtime_error(error);
    }
    return undefined(env);
  });
}

napi_value complete(napi_env env, napi_callback_info info) {
  return guarded(env, info, 3, [&](const auto& argv) {
    auto* bridge = bridge_value(env, argv[0]);
    const auto task = string_value(env, argv[1]);
    const auto result = string_value(env, argv[2]);
    std::size_t consumed = 0;
    const auto task_id = std::stoull(task, &consumed);
    if (consumed != task.size()) throw std::runtime_error("Invalid task id");
    char error[512]{};
    if (!pvm_runtime_complete_effect(bridge->runtime, task_id, result.c_str(), error,
                                     sizeof(error))) {
      throw std::runtime_error(error);
    }
    return undefined(env);
  });
}

napi_value cancel(napi_env env, napi_callback_info info) {
  return guarded(env, info, 1, [&](const auto& argv) {
    pvm_runtime_cancel_all_tasks(bridge_value(env, argv[0])->runtime);
    return undefined(env);
  });
}

napi_value metadata(napi_env env, napi_callback_info info) {
  return guarded(env, info, 1, [&](const auto& argv) {
    auto* bridge = bridge_value(env, argv[0]);
    char error[512]{};
    const auto size =
        pvm_runtime_metadata_json(bridge->runtime, nullptr, 0, error, sizeof(error));
    std::string result(size, '\0');
    if (size == 0 ||
        pvm_runtime_metadata_json(bridge->runtime, result.data(), result.size(), error,
                                  sizeof(error)) != size) {
      throw std::runtime_error(error);
    }
    return string_value(env, result.c_str(), result.size());
  });
}

napi_value snapshot(napi_env env, napi_callback_info info) {
  return guarded(env, info, 1, [&](const auto& argv) {
    auto* bridge = bridge_value(env, argv[0]);
    char error[512]{};
    const auto size =
        pvm_runtime_snapshot_state(bridge->runtime, nullptr, 0, error, sizeof(error));
    void* output = nullptr;
    napi_value result = nullptr;
    check(napi_create_arraybuffer(env, size, &output, &result), "Cannot allocate state buffer");
    if (size == 0 ||
        pvm_runtime_snapshot_state(bridge->runtime, static_cast<std::uint8_t*>(output), size,
                                   error, sizeof(error)) != size) {
      throw std::runtime_error(error);
    }
    return result;
  });
}

napi_value restore(napi_env env, napi_callback_info info) {
  return guarded(env, info, 2, [&](const auto& argv) {
    auto* bridge = bridge_value(env, argv[0]);
    void* data = nullptr;
    std::size_t size = 0;
    check(napi_get_arraybuffer_info(env, argv[1], &data, &size), "State must be an ArrayBuffer");
    char error[512]{};
    if (!pvm_runtime_restore_state(bridge->runtime, static_cast<const std::uint8_t*>(data), size,
                                   error, sizeof(error))) {
      throw std::runtime_error(error);
    }
    return undefined(env);
  });
}

napi_value destroy(napi_env env, napi_callback_info info) {
  return guarded(env, info, 1, [&](const auto& argv) {
    void* raw = nullptr;
    check(napi_get_value_external(env, argv[0], &raw), "Expected runtime handle");
    auto* bridge = static_cast<Bridge*>(raw);
    if (bridge != nullptr) bridge->close();
    return undefined(env);
  });
}

napi_value initialize(napi_env env, napi_value exports) {
  const napi_property_descriptor properties[]{
      {"create", nullptr, create, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"start", nullptr, start, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"dispatch", nullptr, dispatch, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"dispatchValue", nullptr, dispatch_value, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"complete", nullptr, complete, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"cancel", nullptr, cancel, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"metadata", nullptr, metadata, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"snapshot", nullptr, snapshot, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"restore", nullptr, restore, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"destroy", nullptr, destroy, nullptr, nullptr, nullptr, napi_default, nullptr},
  };
  check(napi_define_properties(env, exports, sizeof(properties) / sizeof(properties[0]),
                               properties),
        "Cannot export native module");
  return exports;
}

}  // namespace

NAPI_MODULE(NODE_GYP_MODULE_NAME, initialize)
