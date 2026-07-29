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

void on_ui(void* context, const char* json, std::size_t size) {
  auto& state = *static_cast<HostState*>(context);
  const std::string batch(json, size);
  if (batch.find("\"operation\":\"replace\"") == std::string::npos) {
    std::cerr << "invalid UI batch\n";
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
  pvm_host_callbacks callbacks{&state, on_ui, on_effect, on_async_effect};
  char error[512]{};
  pvm_runtime* runtime =
      pvm_runtime_create(argv[1], argv[2], argv[3], 0, callbacks, error, sizeof(error));
  if (runtime == nullptr || !pvm_runtime_start(runtime, error, sizeof(error)) ||
      !pvm_runtime_dispatch(runtime, node_id("counter_increment"), 1, error, sizeof(error)) ||
      !pvm_runtime_dispatch(runtime, node_id("counter_notify"), 1, error, sizeof(error))) {
    std::cerr << error << '\n';
    pvm_runtime_destroy(runtime);
    return 1;
  }
  state.runtime = runtime;
  if (!pvm_runtime_dispatch_value(runtime, node_id("counter_name"), 2, "Ada", error,
                                  sizeof(error)) ||
      state.last_ui.find("\"value\":\"Ada\"") == std::string::npos) {
    std::cerr << (error[0] == '\0' ? "UI event value assertion failed" : error) << '\n';
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
      !pvm_runtime_restore_state(runtime, snapshot.data(), snapshot.size(), error, sizeof(error)) ||
      pvm_runtime_release(runtime) != 5 || state.ui_batches != 4 || state.effects != 1 ||
      state.async_effects != 1 || state.async_failed) {
    std::cerr << (error[0] == '\0' ? "C ABI assertion failed" : error) << '\n';
    pvm_runtime_destroy(runtime);
    return 1;
  }
  pvm_runtime_destroy(runtime);
  std::cout << "C ABI smoke: PASS\n";
  return 0;
}
