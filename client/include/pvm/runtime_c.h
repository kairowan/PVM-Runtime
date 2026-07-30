#pragma once

#include <stddef.h>
#include <stdint.h>

#if defined(_WIN32)
#define PVM_EXPORT __declspec(dllexport)
#else
#define PVM_EXPORT __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

typedef struct pvm_runtime pvm_runtime;

typedef void (*pvm_ui_batch_callback)(void* context, const char* json, size_t json_size);
// The returned UTF-8 string is copied before the callback returns. NULL reports a host error.
typedef const char* (*pvm_effect_callback)(void* context, const char* capability,
                                          const char* operation, const char* arguments_json);
typedef void (*pvm_async_effect_callback)(void* context, uint64_t task_id,
                                          const char* capability, const char* operation,
                                          const char* arguments_json);
typedef int (*pvm_signature_verify_callback)(
    void* context, const uint8_t* payload, size_t payload_size,
    const uint8_t* signature, size_t signature_size, const char* public_key_path);

typedef struct pvm_host_callbacks {
  void* context;
  pvm_ui_batch_callback on_ui_batch;
  pvm_effect_callback on_effect;
  pvm_async_effect_callback on_async_effect;
} pvm_host_callbacks;

typedef struct pvm_host_callbacks_v2 {
  void* context;
  pvm_ui_batch_callback on_ui_batch;
  pvm_effect_callback on_effect;
  pvm_async_effect_callback on_async_effect;
  pvm_signature_verify_callback on_verify_signature;
} pvm_host_callbacks_v2;

PVM_EXPORT pvm_runtime* pvm_runtime_create(
    const char* module_path, const char* public_key_path, const char* expected_application_id,
    uint64_t minimum_release, pvm_host_callbacks callbacks, char* error, size_t error_capacity);
PVM_EXPORT pvm_runtime* pvm_runtime_create_v2(
    const char* module_path, const char* public_key_path, const char* expected_application_id,
    uint64_t minimum_release, pvm_host_callbacks_v2 callbacks, char* error,
    size_t error_capacity);
// New platform hosts must use v3 so channel/platform/profile bindings are checked at creation.
PVM_EXPORT pvm_runtime* pvm_runtime_create_v3(
    const char* module_path, const char* public_key_path, const char* expected_application_id,
    const char* expected_channel, const char* expected_platform, const char* expected_profile,
    uint64_t minimum_release, pvm_host_callbacks_v2 callbacks, char* error,
    size_t error_capacity);
PVM_EXPORT int pvm_runtime_start(pvm_runtime* runtime, char* error, size_t error_capacity);
PVM_EXPORT int pvm_runtime_dispatch(pvm_runtime* runtime, uint32_t node_id, uint8_t event_type,
                                    char* error, size_t error_capacity);
PVM_EXPORT int pvm_runtime_dispatch_value(pvm_runtime* runtime, uint32_t node_id,
                                          uint8_t event_type, const char* value, char* error,
                                          size_t error_capacity);
// Complete on the same serialized host/UI thread used for start and dispatch.
PVM_EXPORT int pvm_runtime_complete_effect(pvm_runtime* runtime, uint64_t task_id,
                                           const char* result, char* error,
                                           size_t error_capacity);
PVM_EXPORT void pvm_runtime_cancel_all_tasks(pvm_runtime* runtime);
PVM_EXPORT size_t pvm_runtime_snapshot_state(pvm_runtime* runtime, uint8_t* output,
                                             size_t output_capacity, char* error,
                                             size_t error_capacity);
PVM_EXPORT int pvm_runtime_restore_state(pvm_runtime* runtime, const uint8_t* input,
                                         size_t input_size, char* error, size_t error_capacity);
PVM_EXPORT size_t pvm_runtime_metadata_json(pvm_runtime* runtime, char* output,
                                            size_t output_capacity, char* error,
                                            size_t error_capacity);
PVM_EXPORT uint64_t pvm_runtime_release(const pvm_runtime* runtime);
PVM_EXPORT void pvm_runtime_destroy(pvm_runtime* runtime);

#ifdef __cplusplus
}
#endif
