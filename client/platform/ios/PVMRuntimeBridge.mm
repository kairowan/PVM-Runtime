#import "PVMRuntimeBridge.h"

#include "pvm/runtime_c.h"

#include <string>

static NSString* const PVMErrorDomain = @"com.protectedvm.runtime";

@interface PVMRuntimeBridge () {
  pvm_runtime* _runtime;
  std::string _syncResult;
  uint64_t _taskGeneration;
}
@property(nonatomic, copy) PVMUIBatchHandler uiHandler;
@property(nonatomic, copy) PVMSyncEffectHandler syncEffectHandler;
@property(nonatomic, copy) PVMAsyncEffectHandler asyncEffectHandler;
@property(nonatomic, copy) PVMSignatureVerifier signatureVerifier;
- (const char*)performSyncCapability:(const char*)capability
                           operation:(const char*)operation
                       argumentsJSON:(const char*)argumentsJSON;
- (void)performAsyncTask:(uint64_t)taskID
              capability:(const char*)capability
               operation:(const char*)operation
           argumentsJSON:(const char*)argumentsJSON;
@end

static NSError* PVMError(const char* message) {
  NSString* text = [NSString stringWithUTF8String:message];
  if (text == nil) text = @"Unknown runtime error";
  return [NSError errorWithDomain:PVMErrorDomain
                             code:1
                         userInfo:@{NSLocalizedDescriptionKey : text}];
}

static NSString* PVMString(const char* value, size_t size) {
  NSString* result =
      [[NSString alloc] initWithBytes:value length:size encoding:NSUTF8StringEncoding];
  return result == nil ? @"" : result;
}

static NSString* PVMString(const char* value) {
  NSString* result = [NSString stringWithUTF8String:value];
  return result == nil ? @"" : result;
}

static void PVMUI(void* context, const char* json, size_t size) {
  PVMRuntimeBridge* bridge = (__bridge PVMRuntimeBridge*)context;
  bridge.uiHandler(PVMString(json, size));
}

static const char* PVMSyncEffect(void* context, const char* capability, const char* operation,
                                 const char* argumentsJSON) {
  PVMRuntimeBridge* bridge = (__bridge PVMRuntimeBridge*)context;
  return [bridge performSyncCapability:capability
                             operation:operation
                         argumentsJSON:argumentsJSON];
}

static void PVMAsyncEffect(void* context, uint64_t taskID, const char* capability,
                           const char* operation, const char* argumentsJSON) {
  PVMRuntimeBridge* bridge = (__bridge PVMRuntimeBridge*)context;
  [bridge performAsyncTask:taskID
                capability:capability
                 operation:operation
             argumentsJSON:argumentsJSON];
}

static int PVMSignature(void* context, const uint8_t* payload, size_t payloadSize,
                        const uint8_t* signature, size_t signatureSize,
                        const char* publicKeyPath) {
  PVMRuntimeBridge* bridge = (__bridge PVMRuntimeBridge*)context;
  NSData* payloadData = [NSData dataWithBytes:payload length:payloadSize];
  NSData* signatureData = [NSData dataWithBytes:signature length:signatureSize];
  return bridge.signatureVerifier(payloadData, signatureData, PVMString(publicKeyPath)) ? 1 : 0;
}

static int PVMStandaloneSignature(void* context, const uint8_t* payload, size_t payloadSize,
                                  const uint8_t* signature, size_t signatureSize,
                                  const char* publicKeyPath) {
  PVMSignatureVerifier verifier = (__bridge PVMSignatureVerifier)context;
  return verifier([NSData dataWithBytes:payload length:payloadSize],
                  [NSData dataWithBytes:signature length:signatureSize],
                  PVMString(publicKeyPath))
             ? 1
             : 0;
}

@implementation PVMRuntimeBridge

+ (uint64_t)validateModulePath:(NSString*)modulePath
                 publicKeyPath:(NSString*)publicKeyPath
                 applicationID:(NSString*)applicationID
               expectedChannel:(NSString*)expectedChannel
               expectedProfile:(NSString*)expectedProfile
                minimumRelease:(uint64_t)minimumRelease
             signatureVerifier:(PVMSignatureVerifier)signatureVerifier
                         error:(NSError* _Nullable* _Nullable)error {
  PVMSignatureVerifier verifier = [signatureVerifier copy];
  const pvm_host_callbacks_v2 callbacks{
      (__bridge void*)verifier, nullptr, nullptr, nullptr, PVMStandaloneSignature};
  char message[512]{};
  pvm_runtime* runtime =
      pvm_runtime_create_v3(modulePath.fileSystemRepresentation,
                            publicKeyPath.fileSystemRepresentation, applicationID.UTF8String,
                            expectedChannel.UTF8String, "ios", expectedProfile.UTF8String,
                            minimumRelease, callbacks, message, sizeof(message));
  if (runtime == nullptr) {
    if (error != nullptr) *error = PVMError(message);
    return 0;
  }
  const uint64_t release = pvm_runtime_release(runtime);
  pvm_runtime_destroy(runtime);
  return release;
}

- (const char*)performSyncCapability:(const char*)capability
                           operation:(const char*)operation
                       argumentsJSON:(const char*)argumentsJSON {
  NSString* result =
      self.syncEffectHandler(PVMString(capability), PVMString(operation),
                             PVMString(argumentsJSON));
  if (result == nil) return nullptr;
  const char* encoded = result.UTF8String;
  if (encoded == nullptr) return nullptr;
  _syncResult = encoded;
  return _syncResult.c_str();
}

- (void)performAsyncTask:(uint64_t)taskID
              capability:(const char*)capability
               operation:(const char*)operation
           argumentsJSON:(const char*)argumentsJSON {
  __weak PVMRuntimeBridge* weakSelf = self;
  const uint64_t generation = _taskGeneration;
  self.asyncEffectHandler(
      taskID, PVMString(capability), PVMString(operation), PVMString(argumentsJSON),
      ^(NSString* result) {
        dispatch_async(dispatch_get_main_queue(), ^{
          PVMRuntimeBridge* strongSelf = weakSelf;
          if (strongSelf == nil || strongSelf->_runtime == nullptr ||
              strongSelf->_taskGeneration != generation) {
            return;
          }
          NSData* encoded = [result dataUsingEncoding:NSUTF8StringEncoding];
          std::string terminated(static_cast<const char*>(encoded.bytes), encoded.length);
          char error[512]{};
          if (!pvm_runtime_complete_effect(strongSelf->_runtime, taskID, terminated.c_str(), error,
                                           sizeof(error))) {
            NSLog(@"ProtectedVM async completion failed: %@", PVMString(error));
          }
        });
      });
}

- (nullable instancetype)initWithModulePath:(NSString*)modulePath
                              publicKeyPath:(NSString*)publicKeyPath
                              applicationID:(NSString*)applicationID
                            expectedChannel:(NSString*)expectedChannel
                            expectedProfile:(NSString*)expectedProfile
                             minimumRelease:(uint64_t)minimumRelease
                          signatureVerifier:(PVMSignatureVerifier)signatureVerifier
                                  uiHandler:(PVMUIBatchHandler)uiHandler
                          syncEffectHandler:(PVMSyncEffectHandler)syncEffectHandler
                         asyncEffectHandler:(PVMAsyncEffectHandler)asyncEffectHandler
                                      error:(NSError* _Nullable* _Nullable)error {
  self = [super init];
  if (self == nil) return nil;
  _uiHandler = [uiHandler copy];
  _syncEffectHandler = [syncEffectHandler copy];
  _asyncEffectHandler = [asyncEffectHandler copy];
  _signatureVerifier = [signatureVerifier copy];
  const pvm_host_callbacks_v3 callbacks{
      (__bridge void*)self, PVMUI, PVMSyncEffect, PVMAsyncEffect, PVMSignature,
      PVM_UI_WIRE_V2};
  char message[512]{};
  _runtime = pvm_runtime_create_v4(
      modulePath.fileSystemRepresentation, publicKeyPath.fileSystemRepresentation,
      applicationID.UTF8String, expectedChannel.UTF8String, "ios",
      expectedProfile.UTF8String, minimumRelease, callbacks, message, sizeof(message));
  if (_runtime == nullptr) {
    if (error != nullptr) *error = PVMError(message);
    return nil;
  }
  return self;
}

- (void)dealloc {
  if (_runtime != nullptr) {
    ++_taskGeneration;
    pvm_runtime_cancel_all_tasks(_runtime);
    pvm_runtime_destroy(_runtime);
    _runtime = nullptr;
  }
}

- (NSString*)metadataJSON {
  NSAssert(_runtime != nullptr, @"Runtime is closed");
  char error[512]{};
  const size_t size = pvm_runtime_metadata_json(_runtime, nullptr, 0, error, sizeof(error));
  NSMutableData* data = [NSMutableData dataWithLength:size];
  if (size == 0 ||
      pvm_runtime_metadata_json(_runtime, static_cast<char*>(data.mutableBytes), size, error,
                                sizeof(error)) != size) {
    return @"{}";
  }
  NSString* result = [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding];
  return result == nil ? @"{}" : result;
}

- (uint64_t)moduleRelease {
  return _runtime == nullptr ? 0 : pvm_runtime_release(_runtime);
}

- (BOOL)start:(NSError* _Nullable* _Nullable)error {
  NSAssert(NSThread.isMainThread, @"Runtime must start on the main thread");
  char message[512]{};
  if (_runtime != nullptr && pvm_runtime_start(_runtime, message, sizeof(message))) return YES;
  if (error != nullptr) *error = PVMError(message);
  return NO;
}

- (BOOL)dispatchNode:(uint32_t)nodeID
               event:(uint8_t)event
               error:(NSError* _Nullable* _Nullable)error {
  return [self dispatchNode:nodeID event:event value:nil error:error];
}

- (BOOL)dispatchNode:(uint32_t)nodeID
               event:(uint8_t)event
               value:(nullable NSString*)value
               error:(NSError* _Nullable* _Nullable)error {
  NSAssert(NSThread.isMainThread, @"Runtime events must use the main thread");
  char message[512]{};
  const BOOL dispatched =
      _runtime != nullptr &&
      (value == nil
           ? pvm_runtime_dispatch(_runtime, nodeID, event, message, sizeof(message))
           : pvm_runtime_dispatch_value(_runtime, nodeID, event, value.UTF8String, message,
                                        sizeof(message)));
  if (dispatched) {
    return YES;
  }
  if (error != nullptr) *error = PVMError(message);
  return NO;
}

- (nullable NSData*)snapshotState:(NSError* _Nullable* _Nullable)error {
  NSAssert(NSThread.isMainThread, @"Runtime state must use the main thread");
  char message[512]{};
  const size_t size =
      _runtime == nullptr
          ? 0
          : pvm_runtime_snapshot_state(_runtime, nullptr, 0, message, sizeof(message));
  NSMutableData* state = [NSMutableData dataWithLength:size];
  if (size == 0 ||
      pvm_runtime_snapshot_state(_runtime, static_cast<uint8_t*>(state.mutableBytes), size, message,
                                 sizeof(message)) != size) {
    if (error != nullptr) *error = PVMError(message);
    return nil;
  }
  return state;
}

- (BOOL)restoreState:(NSData*)state error:(NSError* _Nullable* _Nullable)error {
  NSAssert(NSThread.isMainThread, @"Runtime state must use the main thread");
  char message[512]{};
  if (_runtime != nullptr &&
      pvm_runtime_restore_state(_runtime, static_cast<const uint8_t*>(state.bytes), state.length,
                                message, sizeof(message))) {
    return YES;
  }
  if (error != nullptr) *error = PVMError(message);
  return NO;
}

- (void)cancelAllTasks {
  NSAssert(NSThread.isMainThread, @"Runtime cancellation must use the main thread");
  if (_runtime != nullptr) {
    ++_taskGeneration;
    pvm_runtime_cancel_all_tasks(_runtime);
  }
}

- (void)close {
  NSAssert(NSThread.isMainThread, @"Runtime close must use the main thread");
  if (_runtime != nullptr) {
    ++_taskGeneration;
    pvm_runtime_cancel_all_tasks(_runtime);
    pvm_runtime_destroy(_runtime);
    _runtime = nullptr;
  }
}

@end
