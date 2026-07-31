#include "pvm/runtime_c.h"

#include <cstdint>
#include <cstring>
#include <iostream>
#include <string>
#include <vector>

namespace {

struct HostState {
  pvm_runtime* runtime{nullptr};
  int ui_batches{0};
  int effects{0};
  int async_effects{0};
  bool async_failed{false};
  bool invalid_ui{false};
  bool defer_async{false};
  std::string last_ui;
  std::vector<std::uint64_t> pending_tasks;
};

std::uint32_t node_id(const std::string& source_id) {
  std::uint32_t result = 2166136261U;
  for (const unsigned char byte : source_id) {
    result = (result ^ byte) * 16777619U;
  }
  return result;
}

std::uint64_t node_revision(const std::string& batch, std::uint32_t id) {
  const auto marker = "\"id\":" + std::to_string(id) + ",\"revision\":";
  const auto start = batch.find(marker);
  if (start == std::string::npos) return 0;
  const auto value = start + marker.size();
  const auto end = batch.find_first_not_of("0123456789", value);
  return std::stoull(batch.substr(value, end - value));
}

bool changed_node(const std::string& batch, std::uint32_t id) {
  const auto start = batch.find("\"changed\":[");
  if (start == std::string::npos) return false;
  const auto end = batch.find(']', start);
  if (end == std::string::npos) return false;
  const auto values = ',' + batch.substr(start + std::strlen("\"changed\":["),
                                         end - start - std::strlen("\"changed\":[")) +
                      ',';
  return values.find(',' + std::to_string(id) + ',') != std::string::npos;
}

void on_ui(void* context, const char* json, std::size_t size) {
  auto& state = *static_cast<HostState*>(context);
  const std::string batch(json, size);
  if (batch.find("\"operation\":\"replace\"") == std::string::npos &&
      batch.find("\"operation\":\"patch\"") == std::string::npos) {
    state.invalid_ui = true;
    return;
  }
  state.last_ui = batch;
  ++state.ui_batches;
}

const char* on_effect(void* context, const char* capability, const char* operation,
                      const char* arguments_json) {
  auto& state = *static_cast<HostState*>(context);
  if (std::strcmp(capability, "ui.toast") != 0 || std::strcmp(operation, "show") != 0 ||
      arguments_json[0] != '[') {
    return nullptr;
  }
  ++state.effects;
  return "ok";
}

void on_async_effect(void* context, std::uint64_t task_id, const char* capability,
                     const char* operation, const char* arguments_json) {
  auto& state = *static_cast<HostState*>(context);
  if (std::strcmp(capability, "storage.kv") != 0 || std::strcmp(operation, "get") != 0 ||
      arguments_json[0] != '[') {
    state.async_failed = true;
    return;
  }
  if (state.defer_async) {
    state.pending_tasks.push_back(task_id);
    return;
  }
  char error[256]{};
  if (!pvm_runtime_complete_effect(state.runtime, task_id, "Loaded", error, sizeof(error))) {
    state.async_failed = true;
    return;
  }
  ++state.async_effects;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc != 4) {
    std::cerr << "usage: pvm_c_api_smoke MODULE PUBLIC_KEY APP_ID\n";
    return 2;
  }
  HostState state;
  pvm_host_callbacks_v2 callbacks{
      &state, on_ui, on_effect, on_async_effect, nullptr};
  char error[512]{};
  pvm_runtime* mismatched =
      pvm_runtime_create_v3(argv[1], argv[2], argv[3], "enterprise", "ios",
                            "online_provisioned", 0, callbacks, error, sizeof(error));
  if (mismatched != nullptr ||
      std::string(error).find("platform binding mismatch") == std::string::npos) {
    std::cerr << "C ABI platform binding assertion failed\n";
    pvm_runtime_destroy(mismatched);
    return 1;
  }
  pvm_runtime* runtime =
      pvm_runtime_create_v3(argv[1], argv[2], argv[3], "enterprise", "desktop",
                            "online_provisioned", 0, callbacks, error, sizeof(error));
  if (runtime == nullptr) {
    std::cerr << error << '\n';
    return 1;
  }
  if (pvm_runtime_dispatch(runtime, node_id("counter_increment"), 1, error, sizeof(error)) ||
      std::string(error).find("not started") == std::string::npos) {
    std::cerr << "pre-start dispatch assertion failed\n";
    pvm_runtime_destroy(runtime);
    return 1;
  }
  const auto initial_size =
      pvm_runtime_snapshot_state(runtime, nullptr, 0, error, sizeof(error));
  std::vector<std::uint8_t> initial(initial_size);
  if (initial.empty() ||
      pvm_runtime_snapshot_state(runtime, initial.data(), initial.size(), error, sizeof(error)) !=
          initial.size() ||
      !pvm_runtime_restore_state(runtime, initial.data(), initial.size(), error, sizeof(error)) ||
      !pvm_runtime_start(runtime, error, sizeof(error)) ||
      pvm_runtime_start(runtime, error, sizeof(error)) ||
      std::string(error).find("already started") == std::string::npos) {
    std::cerr << error << '\n';
    pvm_runtime_destroy(runtime);
    return 1;
  }
  state.runtime = runtime;
  const auto initial_title_revision =
      node_revision(state.last_ui, node_id("counter_title"));
  const auto initial_button_revision =
      node_revision(state.last_ui, node_id("counter_notify"));
  if (state.last_ui.find("\"structureChanged\":true") == std::string::npos) {
    std::cerr << "initial UI structure marker assertion failed\n";
    pvm_runtime_destroy(runtime);
    return 1;
  }
  if (!pvm_runtime_dispatch(runtime, node_id("counter_increment"), 1, error, sizeof(error)) ||
      node_revision(state.last_ui, node_id("counter_title")) <= initial_title_revision ||
      node_revision(state.last_ui, node_id("counter_notify")) != initial_button_revision ||
      state.last_ui.find("\"structureChanged\":false") == std::string::npos ||
      !changed_node(state.last_ui, node_id("counter_title")) ||
      changed_node(state.last_ui, node_id("counter_notify")) ||
      !pvm_runtime_dispatch(runtime, node_id("counter_notify"), 1, error, sizeof(error))) {
    std::cerr << (error[0] == '\0' ? "UI revision assertion failed" : error) << '\n';
    pvm_runtime_destroy(runtime);
    return 1;
  }
  if (!pvm_runtime_dispatch_value(runtime, node_id("counter_name"), 2, "Ada", error,
                                  sizeof(error)) ||
      state.last_ui.find("\"value\":\"Ada\"") == std::string::npos) {
    std::cerr << (error[0] == '\0' ? "UI event value assertion failed" : error) << '\n';
    pvm_runtime_destroy(runtime);
    return 1;
  }
  const auto batches_after_name_change = state.ui_batches;
  for (int index = 0; index < 64; ++index) {
    if (!pvm_runtime_dispatch_value(runtime, node_id("counter_name"), 2, "Ada", error,
                                    sizeof(error))) {
      std::cerr << error << '\n';
      pvm_runtime_destroy(runtime);
      return 1;
    }
  }
  if (state.ui_batches != batches_after_name_change) {
    std::cerr << "unchanged UI was emitted again\n";
    pvm_runtime_destroy(runtime);
    return 1;
  }
  if (!pvm_runtime_dispatch(runtime, node_id("counter_load_status"), 1, error, sizeof(error))) {
    std::cerr << error << '\n';
    pvm_runtime_destroy(runtime);
    return 1;
  }
  const auto metadata_size =
      pvm_runtime_metadata_json(runtime, nullptr, 0, error, sizeof(error));
  std::string metadata(metadata_size, '\0');
  if (metadata.empty() ||
      pvm_runtime_metadata_json(runtime, metadata.data(), metadata.size(), error,
                                sizeof(error)) != metadata.size() ||
      metadata.find("\"channel\":\"enterprise\"") == std::string::npos ||
      metadata.find("\"storage.kv\"") == std::string::npos ||
      metadata.find("\"capabilityVersions\":{\"storage.kv\":1") == std::string::npos ||
      metadata.find("\"platform\":\"desktop\"") == std::string::npos) {
    std::cerr << (error[0] == '\0' ? "metadata assertion failed" : error) << '\n';
    pvm_runtime_destroy(runtime);
    return 1;
  }
  state.defer_async = true;
  for (int index = 0; index < 8; ++index) {
    if (!pvm_runtime_dispatch(runtime, node_id("counter_load_status"), 1, error,
                              sizeof(error))) {
      std::cerr << error << '\n';
      pvm_runtime_destroy(runtime);
      return 1;
    }
  }
  if (pvm_runtime_dispatch(runtime, node_id("counter_load_status"), 1, error, sizeof(error)) ||
      std::string(error).find("task budget") == std::string::npos ||
      state.pending_tasks.size() != 8) {
    std::cerr << "asynchronous task budget assertion failed\n";
    pvm_runtime_destroy(runtime);
    return 1;
  }
  pvm_runtime_cancel_all_tasks(runtime);
  if (pvm_runtime_complete_effect(runtime, state.pending_tasks.front(), "late", error,
                                  sizeof(error)) ||
      std::string(error).find("cancelled") == std::string::npos) {
    std::cerr << "asynchronous cancellation assertion failed\n";
    pvm_runtime_destroy(runtime);
    return 1;
  }
  const auto snapshot_size =
      pvm_runtime_snapshot_state(runtime, nullptr, 0, error, sizeof(error));
  std::vector<std::uint8_t> snapshot(snapshot_size);
  if (snapshot.empty() ||
      pvm_runtime_snapshot_state(runtime, snapshot.data(), snapshot.size(), error, sizeof(error)) !=
          snapshot.size() ||
      pvm_runtime_restore_state(runtime, snapshot.data(), snapshot.size(), error, sizeof(error)) ||
      std::string(error).find("before runtime start") == std::string::npos ||
      pvm_runtime_release(runtime) != 5 || state.ui_batches != 4 || state.effects != 1 ||
      state.async_effects != 1 || state.async_failed || state.invalid_ui ||
      state.last_ui.find("\"wireVersion\"") != std::string::npos ||
      state.last_ui.find("\"root\":") == std::string::npos) {
    std::cerr << (error[0] == '\0' ? "C ABI assertion failed" : error) << '\n';
    pvm_runtime_destroy(runtime);
    return 1;
  }
  pvm_runtime_destroy(runtime);

  HostState patch_state;
  pvm_host_callbacks_v3 patch_callbacks{
      &patch_state,
      on_ui,
      on_effect,
      on_async_effect,
      nullptr,
      PVM_UI_WIRE_V2,
  };
  pvm_runtime* invalid_wire =
      pvm_runtime_create_v4(argv[1], argv[2], argv[3], "enterprise", "desktop",
                            "online_provisioned", 0,
                            pvm_host_callbacks_v3{&patch_state, on_ui, on_effect,
                                                  on_async_effect, nullptr, 99},
                            error, sizeof(error));
  if (invalid_wire != nullptr ||
      std::string(error).find("unsupported UI wire version") == std::string::npos) {
    std::cerr << "C ABI wire version assertion failed\n";
    pvm_runtime_destroy(invalid_wire);
    return 1;
  }
  pvm_runtime* patch_runtime =
      pvm_runtime_create_v4(argv[1], argv[2], argv[3], "enterprise", "desktop",
                            "online_provisioned", 0, patch_callbacks, error, sizeof(error));
  if (patch_runtime == nullptr || !pvm_runtime_start(patch_runtime, error, sizeof(error)) ||
      patch_state.last_ui.find("\"wireVersion\":2") == std::string::npos ||
      patch_state.last_ui.find("\"operation\":\"replace\"") == std::string::npos ||
      patch_state.last_ui.find("\"root\":") == std::string::npos) {
    std::cerr << (error[0] == '\0' ? "C ABI v4 initial batch assertion failed" : error) << '\n';
    pvm_runtime_destroy(patch_runtime);
    return 1;
  }
  const auto full_batch_size = patch_state.last_ui.size();
  if (!pvm_runtime_dispatch(patch_runtime, node_id("counter_increment"), 1, error,
                            sizeof(error)) ||
      patch_state.last_ui.find("\"operation\":\"patch\"") == std::string::npos ||
      patch_state.last_ui.find("\"root\":") != std::string::npos ||
      patch_state.last_ui.find("\"rootId\":") == std::string::npos ||
      patch_state.last_ui.find("\"nodes\":[") == std::string::npos ||
      patch_state.last_ui.find("\"revisions\":[") == std::string::npos ||
      !changed_node(patch_state.last_ui, node_id("counter_title")) ||
      patch_state.last_ui.size() >= full_batch_size || patch_state.invalid_ui) {
    std::cerr << (error[0] == '\0' ? "C ABI v4 patch assertion failed" : error) << '\n';
    pvm_runtime_destroy(patch_runtime);
    return 1;
  }
  pvm_runtime_destroy(patch_runtime);
  std::cout << "C ABI smoke: PASS\n";
  return 0;
}
