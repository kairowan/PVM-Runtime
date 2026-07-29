# Android、iOS 与 HarmonyOS 集成

三端共用 [`client/include/pvm/runtime_c.h`](../client/include/pvm/runtime_c.h) 和同一套 C++17 VM。平台层只负责：

1. 提供 Ed25519 验签实现。
2. 管理模块下载、文件保护、LKG 和 release floor。
3. 把中立 UI Tree 映射到目标 UI 框架。
4. 注册并执行版本化 Capability。
5. 在正确线程转发事件、异步结果和生命周期。

不要在 JNI、Objective-C++ 或 Node-API 中复制字节码解释逻辑。

## 共享启动流程

```mermaid
sequenceDiagram
    participant App
    participant Store as Module Store
    participant VM as C++ Runtime
    participant Registry as Capability Registry
    participant Renderer

    App->>Store: refresh or lastKnownGood
    Store->>Store: verify signed Manifest
    Store->>VM: preload module + release floor
    VM-->>Store: verified release/metadata
    Store-->>App: immutable local module path
    App->>VM: create_v2
    VM-->>App: Runtime policy metadata
    App->>Registry: apply capability versions
    App->>VM: restore state
    App->>VM: start
    VM->>Renderer: replace UI Tree
```

宿主必须先安装验签器和 Capability，再启动 VM。

## Module Store 合同

所有平台实现必须满足：

- 生产模块服务只允许 HTTPS；明文 HTTP 仅限显式启用的 localhost 开发环境。
- Manifest 最大 64 KiB，必须验证 Ed25519 信封。
- 校验 `application/channel/platform/profile/release` 绑定。
- 最低序号为 `max(installed release, minimumRelease)`。
- `module_url` 必须与服务端同源，并严格等于 `/v1/modules/<sha256>.pvm`。
- 模块最大 16 MiB，先写临时文件，再校验大小、Hash、签名和字节码。
- VM 返回 release 必须与签名 Manifest 一致。
- 只有完整验证后才能原子切换。
- LKG 必须满足安装包 release floor。
- 缓存至少保留当前和上一已验证版本。

## Android

### 已提供

- `PvmRuntimeHost.kt`：Runtime 生命周期、UI 批次与 Effect。
- `PvmModuleStore.kt`：Manifest 验签、HTTPS 下载、原子 LKG。
- `PvmCrypto.kt`：平台/注入式 Ed25519。
- `PvmModuleValidator.kt`：JNI 预加载验证。
- `AndroidViewRenderer.kt`：View Renderer。
- `compose/PvmComposeRenderer.kt`：Compose/CMP 适配接口。
- `CapabilityRegistry.kt` 与 `BasicAndroidCapabilities.kt`。
- `pvm_jni.cpp` 与 Android CMake。

### 初始化 Module Store

```kotlin
val store =
    PvmModuleStore(
        root = File(context.noBackupFilesDir, "pvm"),
        publicKeyPath = publicKeyFile.absolutePath,
        applicationId = context.packageName,
        channel = "production",
        profile = "online_provisioned",
        serverBase = "https://modules.example.com",
        activationToken = activationToken,
        installationId = installationId,
        minimumRelease = BuildConfig.PVM_MINIMUM_RELEASE,
    )
```

`refresh()` 必须在工作线程调用。渲染批次应切回主线程；不要在 UI 线程执行网络或模块预加载。

### Ed25519

Android 平台表只保证 Ed25519 `Signature` 在 API 33+ 可用。API 24–32 必须在创建 Store/Runtime 前安装项目已审计的 Provider：

```kotlin
PvmCrypto.installVerifier { keyPath, payload, signature ->
    auditedProvider.verify(keyPath, payload, signature)
}
```

参考：[Android Signature 算法表](https://developer.android.com/reference/java/security/Signature)。

### 文件和打包

- Module Store 根目录使用内部 `noBackupFilesDir`，不要使用外部存储。
- 当前实现对模块和状态应用 `0600`。
- Offline Sealed 的 `module.pvm`、公钥和 bootstrap 可放入 APK 或 AAB 的受保护资源目录；APK 用于直接安装/测试/部分企业分发，AAB 用于 Google Play 生成设备 APK。
- Release 开启 R8 全量优化，并保留 consumer rules 中需要的 native callback。
- NDK 产物是包含完整 Runtime 的 `libpvm_android.so`。
- Capability manifest 生成的权限必须在打包时合并，远程模块不能新增权限。

仓库的 `make delivery-matrix` 只生成 Android Gradle 工程所需的嵌入输入，并在 `bootstrap.json.packageFormats` 中声明 `["apk", "aab"]`；由于仓库不包含业务 App 的 Gradle 工程、application ID 签名配置和 keystore，它不会声称已经生成可安装 APK/AAB。

## iOS

### 已提供

- `PVMRuntimeBridge.mm/.h`：ARC Objective-C++ 桥和 C ABI。
- `PVMModuleStore.swift`：actor Module Store。
- `PVMPlatformCrypto.swift`：CryptoKit Ed25519。
- `PVMUIKitRenderer.swift` 与 `PVMSwiftUIRenderer.swift`。
- `PVMCapabilityRegistry.swift` 与基础 Capability。

### Module Store 配置

```swift
let configuration = PVMModuleStore.Configuration(
    root: appSupport.appendingPathComponent("pvm", isDirectory: true),
    publicKeyPath: publicKeyURL.path,
    applicationId: Bundle.main.bundleIdentifier!,
    channel: "production",
    profile: "online_provisioned",
    server: URL(string: "https://modules.example.com")!,
    activationToken: activationToken,
    installationId: installationId,
    minimumRelease: minimumRelease
)
```

创建 Store 时传入 validator closure，由 Objective-C++ Bridge/C ABI 预加载临时模块并返回模块 release。Store 会要求该值与 Manifest 一致。

### 线程和生命周期

- `PVMModuleStore` 是 actor，网络和缓存状态串行化。
- UI Renderer 必须在主线程应用 UI Tree。
- Objective-C++ Bridge 持有 `pvm_runtime*`，异步 completion 回到宿主串行上下文后再恢复 VM。
- 页面退出、场景关闭或模块替换前调用任务取消。

### 文件和打包

- 模块使用 `completeUntilFirstUserAuthentication`。
- 状态文件使用完整文件保护和原子写。
- 生产建议把 Runtime/Bridge 封装为静态 XCFramework；不从网络下载 Framework。
- CryptoKit 验证内置 X.509 SubjectPublicKeyInfo Ed25519 公钥。
- Capability 生成的 Usage Description/entitlement 必须进入 App 审核产物。

## HarmonyOS

### 已提供

- `pvm_napi.cpp`：标准 Node-API 桥。
- `PvmRuntimeHost.ets`：ArkTS Runtime/Capability Host。
- `PvmModuleStore.ets`：签名 Manifest、缓存与 LKG。
- `ArkUiRenderer.ets`：ArkUI 工厂接口。
- Kuikly Renderer 适配基线。

### App 必须注入

`PvmModuleStore` 构造时需要：

- `ModuleTransport`
- `ModuleFiles`
- `ModuleValidator`
- `publicKeyPath`
- `ModuleSignatureVerifier`
- `minimumRelease`

`ModuleFiles` 的这些方法不能为空操作：

```text
writeTextAtomic / writeBytesAtomic / moveAtomic
protectAtRest
sha256
decodeBase64
decodeUtf8
```

其中 Base64/UTF-8 解码必须保留原始 payload 字节，不能通过 JavaScript 字符串往返后再验签。

### 线程和平台边界

- ArkTS Host 把 UI 批次交给项目 ArkUI/Kuikly Renderer。
- Node-API 回调和 VM 生命周期必须在宿主选定的串行上下文中使用。
- `SignatureVerifier` 由目标 DevEco/Harmony Crypto 或 HUKS Adapter 实现。
- HUKS 可保护缓存密钥；HAP/HSP/远程资源策略仍由 Profile 与发布流水线约束。

当前机器没有 DevEco/HarmonyOS SDK，因此仓库门禁只编译可移植 Node-API C++ 并检查 ArkTS 合同，不能声称 HAP 或真机验证。

## C ABI 生命周期

推荐使用 v2 callbacks：

1. 安装 `pvm_host_callbacks_v2`，包括签名验证回调。
2. 调用 `pvm_runtime_create_v2`，完成模块签名、绑定、防回滚和字节码验证。
3. 读取 Runtime metadata，并让 Capability Registry 检查最低版本。
4. 可选调用 `pvm_runtime_restore_state`。
5. 调用 `pvm_runtime_start`。
6. tap/appear 等无值事件调用 `pvm_runtime_dispatch`；Input/Switch 的
   change/submit 调用 `pvm_runtime_dispatch_value`。
7. 异步结果调用 `pvm_runtime_complete_effect`。
8. 生命周期结束调用 `pvm_runtime_cancel_all_tasks`。
9. 两次调用 `pvm_runtime_snapshot_state` 获取长度和内容，并原子持久化。
10. 调用 `pvm_runtime_destroy`。

旧的 `pvm_runtime_create` 为 ABI 兼容保留；新移动端集成应使用带平台验签器的 v2。

`pvm_runtime_dispatch_value` 的值在调用期间被复制，并受模块
`max_state_bytes` 预算限制。DSL 处理器用 PVBC v5 `event.value` 读取它；对没有值的
事件执行该指令会明确失败。

## UI Renderer 合同

Renderer 接收的是结构树而不是平台对象：

```text
type
numeric node id
properties
registered events
children
```

要求：

- 属性批量应用，避免逐属性 JNI/Node-API 往返。
- 可访问性标签、动态字体和 RTL 由 Renderer 正确映射。
- `NativeSurface` 只承载宿主已注册类型。
- 地图手势、视频帧、相机预览等高频数据留在原生侧。
- Renderer conformance 检查结构语义，不要求跨平台像素完全一致。

## Capability 合同

Host IDL 生成 Kotlin、Swift、ArkTS 和 C++ 接口。Registry 必须：

- 注册 capability ID、版本、同步/异步类型。
- 在 Runtime 启动前应用模块 policy。
- 拒绝未声明、缺失或版本不足的能力。
- 对网络域名、存储 scope、系统权限和用户授权做宿主侧检查。
- 把平台错误转换为结构化结果，不向 DSL 暴露真实平台指针。

## 接入验收

- [ ] 生产公钥和 `minimumRelease` 固定进目标 App 配置。
- [ ] Module Store 使用内部受保护目录。
- [ ] Manifest/模块使用同一信任根或明确的轮换策略。
- [ ] UI、VM、网络和异步 completion 的线程规则明确。
- [ ] Capability 权限、隐私声明、版本和降级 UI 完成。
- [ ] App 冷启动优先加载 LKG，后台刷新不阻塞首屏。
- [ ] 损坏模块、错误签名、网络中断和 304 无缓存均有测试。
- [ ] Android/iOS/HarmonyOS 目标设备完成性能和生命周期验证。
