#include <jni.h>

#include "pvm/runtime_c.h"

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace {

struct JniContext {
  JavaVM* vm{nullptr};
};

struct Bridge : JniContext {
  jobject host{nullptr};
  jmethodID on_ui{nullptr};
  jmethodID on_effect{nullptr};
  jmethodID on_async_effect{nullptr};
  pvm_runtime* runtime{nullptr};
  std::string sync_result;
};

class ScopedEnv {
 public:
  explicit ScopedEnv(JavaVM* vm) : vm_(vm) {
    const auto status = vm_->GetEnv(reinterpret_cast<void**>(&env_), JNI_VERSION_1_6);
    if (status == JNI_EDETACHED) {
      attached_ = vm_->AttachCurrentThread(&env_, nullptr) == JNI_OK;
    }
  }
  ~ScopedEnv() {
    if (attached_) vm_->DetachCurrentThread();
  }
  JNIEnv* get() const { return env_; }

 private:
  JavaVM* vm_;
  JNIEnv* env_{nullptr};
  bool attached_{false};
};

void throw_runtime(JNIEnv* env, const std::string& message) {
  const auto type = env->FindClass("java/lang/IllegalStateException");
  if (type != nullptr) env->ThrowNew(type, message.c_str());
}

jstring new_utf8(JNIEnv* env, const char* value, std::size_t size) {
  const auto bytes = env->NewByteArray(static_cast<jsize>(size));
  if (bytes == nullptr) return nullptr;
  env->SetByteArrayRegion(bytes, 0, static_cast<jsize>(size),
                          reinterpret_cast<const jbyte*>(value));
  const auto string_class = env->FindClass("java/lang/String");
  const auto constructor =
      env->GetMethodID(string_class, "<init>", "([BLjava/lang/String;)V");
  const auto charset = env->NewStringUTF("UTF-8");
  const auto result =
      static_cast<jstring>(env->NewObject(string_class, constructor, bytes, charset));
  env->DeleteLocalRef(charset);
  env->DeleteLocalRef(string_class);
  env->DeleteLocalRef(bytes);
  return result;
}

jstring new_utf8(JNIEnv* env, const char* value) {
  return new_utf8(env, value, std::char_traits<char>::length(value));
}

std::string to_utf8(JNIEnv* env, jstring value) {
  if (value == nullptr) return {};
  const auto charset_class = env->FindClass("java/nio/charset/StandardCharsets");
  const auto utf8_field =
      env->GetStaticFieldID(charset_class, "UTF_8", "Ljava/nio/charset/Charset;");
  const auto charset = env->GetStaticObjectField(charset_class, utf8_field);
  const auto string_class = env->FindClass("java/lang/String");
  const auto get_bytes =
      env->GetMethodID(string_class, "getBytes", "(Ljava/nio/charset/Charset;)[B");
  const auto bytes =
      static_cast<jbyteArray>(env->CallObjectMethod(value, get_bytes, charset));
  const auto length = env->GetArrayLength(bytes);
  std::string result(static_cast<std::size_t>(length), '\0');
  env->GetByteArrayRegion(bytes, 0, length, reinterpret_cast<jbyte*>(result.data()));
  env->DeleteLocalRef(bytes);
  env->DeleteLocalRef(string_class);
  env->DeleteLocalRef(charset);
  env->DeleteLocalRef(charset_class);
  return result;
}

void ui_callback(void* context, const char* json, std::size_t size) {
  auto& bridge = *static_cast<Bridge*>(context);
  ScopedEnv scoped(bridge.vm);
  auto* env = scoped.get();
  if (env == nullptr) return;
  const auto encoded = new_utf8(env, json, size);
  env->CallVoidMethod(bridge.host, bridge.on_ui, encoded);
  env->DeleteLocalRef(encoded);
}

const char* effect_callback(void* context, const char* capability, const char* operation,
                            const char* arguments_json) {
  auto& bridge = *static_cast<Bridge*>(context);
  ScopedEnv scoped(bridge.vm);
  auto* env = scoped.get();
  if (env == nullptr) return nullptr;
  const auto cap = new_utf8(env, capability);
  const auto op = new_utf8(env, operation);
  const auto args = new_utf8(env, arguments_json);
  const auto result =
      static_cast<jstring>(env->CallObjectMethod(bridge.host, bridge.on_effect, cap, op, args));
  env->DeleteLocalRef(args);
  env->DeleteLocalRef(op);
  env->DeleteLocalRef(cap);
  if (env->ExceptionCheck() || result == nullptr) return nullptr;
  bridge.sync_result = to_utf8(env, result);
  env->DeleteLocalRef(result);
  return bridge.sync_result.c_str();
}

void async_effect_callback(void* context, std::uint64_t task_id, const char* capability,
                           const char* operation, const char* arguments_json) {
  auto& bridge = *static_cast<Bridge*>(context);
  ScopedEnv scoped(bridge.vm);
  auto* env = scoped.get();
  if (env == nullptr) return;
  const auto cap = new_utf8(env, capability);
  const auto op = new_utf8(env, operation);
  const auto args = new_utf8(env, arguments_json);
  env->CallVoidMethod(bridge.host, bridge.on_async_effect, static_cast<jlong>(task_id), cap, op,
                      args);
  env->DeleteLocalRef(args);
  env->DeleteLocalRef(op);
  env->DeleteLocalRef(cap);
}

Bridge* from_handle(jlong handle) {
  return reinterpret_cast<Bridge*>(static_cast<std::uintptr_t>(handle));
}

std::vector<std::uint8_t> bytes_from_java(JNIEnv* env, jbyteArray input) {
  const auto length = env->GetArrayLength(input);
  std::vector<std::uint8_t> result(static_cast<std::size_t>(length));
  env->GetByteArrayRegion(input, 0, length, reinterpret_cast<jbyte*>(result.data()));
  return result;
}

int signature_verify_callback(void* context, const std::uint8_t* payload,
                              std::size_t payload_size, const std::uint8_t* signature,
                              std::size_t signature_size, const char* public_key_path) {
  const auto& jni = *static_cast<JniContext*>(context);
  ScopedEnv scoped(jni.vm);
  auto* env = scoped.get();
  if (env == nullptr) return 0;
  const auto type = env->FindClass("com/protectedvm/host/PvmCrypto");
  if (type == nullptr) return 0;
  const auto verify = env->GetStaticMethodID(
      type, "verify", "(Ljava/lang/String;[B[B)Z");
  if (verify == nullptr) {
    env->DeleteLocalRef(type);
    return 0;
  }
  const auto key = new_utf8(env, public_key_path);
  const auto payload_bytes = env->NewByteArray(static_cast<jsize>(payload_size));
  const auto signature_bytes = env->NewByteArray(static_cast<jsize>(signature_size));
  if (key == nullptr || payload_bytes == nullptr || signature_bytes == nullptr) {
    if (signature_bytes != nullptr) env->DeleteLocalRef(signature_bytes);
    if (payload_bytes != nullptr) env->DeleteLocalRef(payload_bytes);
    if (key != nullptr) env->DeleteLocalRef(key);
    env->DeleteLocalRef(type);
    return 0;
  }
  env->SetByteArrayRegion(payload_bytes, 0, static_cast<jsize>(payload_size),
                          reinterpret_cast<const jbyte*>(payload));
  env->SetByteArrayRegion(signature_bytes, 0, static_cast<jsize>(signature_size),
                          reinterpret_cast<const jbyte*>(signature));
  const auto verified =
      env->CallStaticBooleanMethod(type, verify, key, payload_bytes, signature_bytes);
  const auto failed = env->ExceptionCheck();
  env->DeleteLocalRef(signature_bytes);
  env->DeleteLocalRef(payload_bytes);
  env->DeleteLocalRef(key);
  env->DeleteLocalRef(type);
  return !failed && verified == JNI_TRUE;
}

}  // namespace

extern "C" JNIEXPORT jlong JNICALL
Java_com_protectedvm_host_PvmRuntimeHost_nativeCreate(JNIEnv* env, jobject host,
                                                       jstring module_path,
                                                       jstring public_key_path,
                                                       jstring application_id,
                                                       jstring expected_channel,
                                                       jstring expected_profile,
                                                       jlong minimum_release) {
  auto bridge = std::make_unique<Bridge>();
  if (env->GetJavaVM(&bridge->vm) != JNI_OK) {
    throw_runtime(env, "Cannot access JavaVM");
    return 0;
  }
  bridge->host = env->NewGlobalRef(host);
  const auto host_class = env->GetObjectClass(host);
  bridge->on_ui =
      env->GetMethodID(host_class, "onNativeUiBatch", "(Ljava/lang/String;)V");
  bridge->on_effect = env->GetMethodID(
      host_class, "onNativeEffect",
      "(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;");
  bridge->on_async_effect =
      env->GetMethodID(host_class, "onNativeAsyncEffect",
                       "(JLjava/lang/String;Ljava/lang/String;Ljava/lang/String;)V");
  env->DeleteLocalRef(host_class);
  if (bridge->on_ui == nullptr || bridge->on_effect == nullptr ||
      bridge->on_async_effect == nullptr) {
    env->DeleteGlobalRef(bridge->host);
    return 0;
  }

  const auto module = to_utf8(env, module_path);
  const auto key = to_utf8(env, public_key_path);
  const auto app = to_utf8(env, application_id);
  const auto channel = to_utf8(env, expected_channel);
  const auto profile = to_utf8(env, expected_profile);
  char error[512]{};
  const pvm_host_callbacks_v3 callbacks{
      bridge.get(), ui_callback, effect_callback, async_effect_callback,
      signature_verify_callback, PVM_UI_WIRE_V2};
  bridge->runtime =
      pvm_runtime_create_v4(
          module.c_str(), key.c_str(), app.c_str(), channel.c_str(), "android",
          profile.c_str(), static_cast<std::uint64_t>(minimum_release), callbacks, error,
          sizeof(error));
  if (bridge->runtime == nullptr) {
    env->DeleteGlobalRef(bridge->host);
    throw_runtime(env, error);
    return 0;
  }
  return static_cast<jlong>(reinterpret_cast<std::uintptr_t>(bridge.release()));
}

extern "C" JNIEXPORT jstring JNICALL
Java_com_protectedvm_host_PvmRuntimeHost_nativeMetadata(JNIEnv* env, jobject, jlong handle) {
  auto* bridge = from_handle(handle);
  char error[512]{};
  const auto size =
      pvm_runtime_metadata_json(bridge->runtime, nullptr, 0, error, sizeof(error));
  std::string json(size, '\0');
  if (size == 0 ||
      pvm_runtime_metadata_json(bridge->runtime, json.data(), json.size(), error, sizeof(error)) !=
          size) {
    throw_runtime(env, error);
    return nullptr;
  }
  return new_utf8(env, json.data(), json.size());
}

extern "C" JNIEXPORT void JNICALL
Java_com_protectedvm_host_PvmRuntimeHost_nativeStart(JNIEnv* env, jobject, jlong handle) {
  char error[512]{};
  if (!pvm_runtime_start(from_handle(handle)->runtime, error, sizeof(error))) {
    throw_runtime(env, error);
  }
}

extern "C" JNIEXPORT void JNICALL
Java_com_protectedvm_host_PvmRuntimeHost_nativeDispatch(JNIEnv* env, jobject, jlong handle,
                                                         jlong node_id, jint event) {
  if (node_id <= 0 || static_cast<std::uint64_t>(node_id) > UINT32_MAX) {
    throw_runtime(env, "Invalid VM node id");
    return;
  }
  char error[512]{};
  if (!pvm_runtime_dispatch(from_handle(handle)->runtime, static_cast<std::uint32_t>(node_id),
                            static_cast<std::uint8_t>(event), error, sizeof(error))) {
    throw_runtime(env, error);
  }
}

extern "C" JNIEXPORT void JNICALL
Java_com_protectedvm_host_PvmRuntimeHost_nativeDispatchValue(JNIEnv* env, jobject, jlong handle,
                                                              jlong node_id, jint event,
                                                              jstring value) {
  if (node_id <= 0 || static_cast<std::uint64_t>(node_id) > UINT32_MAX || value == nullptr) {
    throw_runtime(env, "Invalid VM event value arguments");
    return;
  }
  const auto encoded = to_utf8(env, value);
  char error[512]{};
  if (!pvm_runtime_dispatch_value(from_handle(handle)->runtime,
                                  static_cast<std::uint32_t>(node_id),
                                  static_cast<std::uint8_t>(event), encoded.c_str(), error,
                                  sizeof(error))) {
    throw_runtime(env, error);
  }
}

extern "C" JNIEXPORT void JNICALL
Java_com_protectedvm_host_PvmRuntimeHost_nativeComplete(JNIEnv* env, jobject, jlong handle,
                                                         jlong task_id, jstring result) {
  const auto encoded = to_utf8(env, result);
  char error[512]{};
  if (!pvm_runtime_complete_effect(from_handle(handle)->runtime,
                                   static_cast<std::uint64_t>(task_id), encoded.c_str(), error,
                                   sizeof(error))) {
    throw_runtime(env, error);
  }
}

extern "C" JNIEXPORT void JNICALL
Java_com_protectedvm_host_PvmRuntimeHost_nativeCancelTasks(JNIEnv*, jobject, jlong handle) {
  pvm_runtime_cancel_all_tasks(from_handle(handle)->runtime);
}

extern "C" JNIEXPORT jbyteArray JNICALL
Java_com_protectedvm_host_PvmRuntimeHost_nativeSnapshot(JNIEnv* env, jobject, jlong handle) {
  auto* bridge = from_handle(handle);
  char error[512]{};
  const auto size =
      pvm_runtime_snapshot_state(bridge->runtime, nullptr, 0, error, sizeof(error));
  std::vector<std::uint8_t> state(size);
  if (size == 0 ||
      pvm_runtime_snapshot_state(bridge->runtime, state.data(), state.size(), error,
                                 sizeof(error)) != size) {
    throw_runtime(env, error);
    return nullptr;
  }
  const auto result = env->NewByteArray(static_cast<jsize>(state.size()));
  env->SetByteArrayRegion(result, 0, static_cast<jsize>(state.size()),
                          reinterpret_cast<const jbyte*>(state.data()));
  return result;
}

extern "C" JNIEXPORT void JNICALL
Java_com_protectedvm_host_PvmRuntimeHost_nativeRestore(JNIEnv* env, jobject, jlong handle,
                                                        jbyteArray input) {
  const auto state = bytes_from_java(env, input);
  char error[512]{};
  if (!pvm_runtime_restore_state(from_handle(handle)->runtime, state.data(), state.size(), error,
                                 sizeof(error))) {
    throw_runtime(env, error);
  }
}

extern "C" JNIEXPORT void JNICALL
Java_com_protectedvm_host_PvmRuntimeHost_nativeDestroy(JNIEnv* env, jobject, jlong handle) {
  std::unique_ptr<Bridge> bridge(from_handle(handle));
  pvm_runtime_destroy(bridge->runtime);
  env->DeleteGlobalRef(bridge->host);
}

extern "C" JNIEXPORT jlong JNICALL
Java_com_protectedvm_host_PvmModuleValidator_nativeValidate(
    JNIEnv* env, jclass, jstring module_path, jstring public_key_path, jstring application_id,
    jstring expected_channel, jstring expected_profile, jlong minimum_release) {
  const auto module = to_utf8(env, module_path);
  const auto key = to_utf8(env, public_key_path);
  const auto app = to_utf8(env, application_id);
  const auto channel = to_utf8(env, expected_channel);
  const auto profile = to_utf8(env, expected_profile);
  JniContext context;
  if (env->GetJavaVM(&context.vm) != JNI_OK) {
    throw_runtime(env, "Cannot access JavaVM");
    return 0;
  }
  const pvm_host_callbacks_v2 callbacks{
      &context, nullptr, nullptr, nullptr, signature_verify_callback};
  char error[512]{};
  auto* runtime =
      pvm_runtime_create_v3(
          module.c_str(), key.c_str(), app.c_str(), channel.c_str(), "android",
          profile.c_str(), static_cast<std::uint64_t>(minimum_release), callbacks, error,
          sizeof(error));
  if (runtime == nullptr) {
    throw_runtime(env, error);
    return 0;
  }
  const auto release = pvm_runtime_release(runtime);
  pvm_runtime_destroy(runtime);
  return static_cast<jlong>(release);
}
