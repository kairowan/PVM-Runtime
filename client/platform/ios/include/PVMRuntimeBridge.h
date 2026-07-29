#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

typedef void (^PVMUIBatchHandler)(NSString* json);
typedef NSString* _Nullable (^PVMSyncEffectHandler)(
    NSString* capability, NSString* operation, NSString* argumentsJSON);
typedef void (^PVMAsyncEffectHandler)(
    uint64_t taskID, NSString* capability, NSString* operation, NSString* argumentsJSON,
    void (^complete)(NSString* result));
typedef BOOL (^PVMSignatureVerifier)(
    NSData* payload, NSData* signature, NSString* publicKeyPath);

@interface PVMRuntimeBridge : NSObject

+ (uint64_t)validateModulePath:(NSString*)modulePath
                 publicKeyPath:(NSString*)publicKeyPath
                 applicationID:(NSString*)applicationID
                minimumRelease:(uint64_t)minimumRelease
             signatureVerifier:(PVMSignatureVerifier)signatureVerifier
                         error:(NSError* _Nullable* _Nullable)error;

- (nullable instancetype)initWithModulePath:(NSString*)modulePath
                              publicKeyPath:(NSString*)publicKeyPath
                              applicationID:(NSString*)applicationID
                             minimumRelease:(uint64_t)minimumRelease
                          signatureVerifier:(PVMSignatureVerifier)signatureVerifier
                                  uiHandler:(PVMUIBatchHandler)uiHandler
                          syncEffectHandler:(PVMSyncEffectHandler)syncEffectHandler
                         asyncEffectHandler:(PVMAsyncEffectHandler)asyncEffectHandler
                                      error:(NSError* _Nullable* _Nullable)error
    NS_DESIGNATED_INITIALIZER;
- (instancetype)init NS_UNAVAILABLE;

@property(nonatomic, readonly) NSString* metadataJSON;
@property(nonatomic, readonly) uint64_t moduleRelease;

- (BOOL)start:(NSError* _Nullable* _Nullable)error;
- (BOOL)dispatchNode:(uint32_t)nodeID
               event:(uint8_t)event
               error:(NSError* _Nullable* _Nullable)error;
- (BOOL)dispatchNode:(uint32_t)nodeID
               event:(uint8_t)event
               value:(nullable NSString*)value
               error:(NSError* _Nullable* _Nullable)error;
- (nullable NSData*)snapshotState:(NSError* _Nullable* _Nullable)error;
- (BOOL)restoreState:(NSData*)state error:(NSError* _Nullable* _Nullable)error;
- (void)cancelAllTasks;
- (void)close;

@end

NS_ASSUME_NONNULL_END
