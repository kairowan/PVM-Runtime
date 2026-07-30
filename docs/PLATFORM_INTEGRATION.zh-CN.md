[English](PLATFORM_INTEGRATION.md)

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
    App->>VM: create_v3(application/channel/platform/profile/floor)
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
- `current` 状态必须严格校验格式、application/channel/platform/profile、正整数
  release、当前 SHA-256 和最多两项的去重历史；历史第一项必须等于当前 Hash。

## Android

### 已提供

- `PvmRuntimeHost.kt`：Runtime 生命周期、UI 批次与 Effect。
- `PvmModuleStore.kt`：Manifest 验签、HTTPS 下载、原子 LKG。
- `PvmCrypto.kt`：Google Tink Ed25519 默认验签与可注入 verifier。
- `PvmModuleValidator.kt`：JNI 预加载验证。
- `AndroidViewRenderer.kt`：View Renderer。
- `compose/PvmComposeRenderer.kt`：尚未接入当前 Gradle 构建的 Compose/CMP 参考原型。
- `CapabilityRegistry.kt` 与 `BasicAndroidCapabilities.kt`。
- `pvm_jni.cpp` 与 Android CMake。
- `runtime` Gradle Library：发布包含完整 C++ Runtime 的 AAR 和 Maven 元数据。
- `demo` Gradle Application：生成可安装的 Debug APK、Debug AAB 和 R8 smoke APK。

### Gradle 工程与版本

Android 工程位于 `client/platform/android`：

```text
client/platform/android/
├── runtime/     Android Library，复用现有 Kotlin/JNI/CMake 源码
├── demo/        Offline Sealed 演示 App
├── gradle/      校验过 SHA-256 的 Gradle Wrapper
└── gradlew
```

当前经过构建门禁的基线为：

| 项目 | 版本或范围 |
|---|---|
| Android Gradle Plugin | 9.3.1 |
| Gradle | 9.6.1 |
| Kotlin | 2.4.10（AGP 内置） |
| JDK / Kotlin JVM target | 17 |
| compileSdk / Demo targetSdk | 36 |
| Runtime minSdk / Demo minSdk | 24 / 33 |
| NDK | 28.0.13004108 |
| CMake / C++ | 3.22.1 / C++17 |
| ABI | `arm64-v8a`、`x86_64` |

Runtime 的 Android Library 通过 `externalNativeBuild` 调用已有
`client/platform/android/CMakeLists.txt`。CMake 只把共享 C++ 核心编译一次，再链接为
`libpvm_android.so`；不要把解释器源码复制进 App 模块。

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

`runtime` 默认依赖 `com.google.crypto.tink:tink-android:1.23.0`。
`PvmCrypto` 从 X.509 SubjectPublicKeyInfo 公钥中提取 Ed25519 原始公钥，并使用 Tink
验证 Manifest 和 `.pvm` 签名，因此 API 24–32 不依赖平台 JCA 是否提供 Ed25519。

目标 App 如果已有经过审计的硬件、系统或厂商验签实现，可以在创建 Module Store 或
Runtime 前安装一次 verifier；安装后它会覆盖默认 Tink 路径：

```kotlin
PvmCrypto.installVerifier { keyPath, payload, signature ->
    auditedProvider.verify(keyPath, payload, signature)
}
```

不要根据 DSL 或远端配置动态选择 verifier。公钥、verifier 和 release floor 都属于宿主
信任根。

### 构建和验证 Android 产物

在仓库根目录执行：

```bash
make android-demo-check
```

该门禁会完成：

1. 构建桌面验证器。
2. 生成 Android Offline Sealed 模块、公钥和 bootstrap。
3. 运行 Runtime 与 Demo Android Lint。
4. 发布 Release AAR 和本地 Maven 仓库。
5. 构建 Debug APK、Debug AAB 和启用 R8 的非 debuggable smoke APK。
6. 检查 APK/AAB/AAR 的 ABI、签名、模块 Hash、篡改拒绝、Maven 依赖和 16 KiB
   对齐。

产物位于：

```text
dist/android/PVMRuntime-demo-debug.apk
dist/android/PVMRuntime-demo-debug.aab
dist/android/PVMRuntime-demo-minified-smoke.apk
dist/android/pvm-runtime-0.5.0.aar
dist/android/maven/com/protectedvm/pvm-runtime/0.5.0/
```

前两个 Demo 产物和 R8 smoke APK 使用 Android Debug keystore。smoke APK 虽然是
non-debuggable 且经过 R8，但仍然只用于验证 consumer rules、JNI 名称和裁剪后的启动
链路；这些产物都不是生产签名包，不能提交商店或交付客户。

需要在设备上复验 R8 产物时：

```bash
adb install -r dist/android/PVMRuntime-demo-minified-smoke.apk
```

### 在目标 App 中接入 Runtime

本地开发推荐使用生成的 Maven 仓库，因为 POM 会传递 Tink 等外部依赖：

```kotlin
// settings.gradle.kts
dependencyResolutionManagement {
    repositories {
        google()
        mavenCentral()
        maven {
            url = uri("/absolute/path/to/PVM-Runtime/dist/android/maven")
        }
    }
}
```

发布 `v0.5.0` 后，独立项目通过 GitHub Packages 引入预编译 AAR：

```kotlin
maven {
    url = uri("https://maven.pkg.github.com/kairowan/PVM-Runtime")
    credentials {
        username = providers.gradleProperty("gpr.user").orNull
        password = providers.gradleProperty("gpr.key").orNull
    }
}
```

```kotlin
// app/build.gradle.kts
dependencies {
    implementation("com.protectedvm:pvm-runtime:0.5.0")
}
```

如果只能复制裸 AAR，AAR 不携带 Maven POM，目标 App 必须显式补上 Tink：

```kotlin
dependencies {
    implementation(files("libs/pvm-runtime-0.5.0.aar"))
    implementation("com.google.crypto.tink:tink-android:1.23.0")
}
```

AAR 已携带 JNI/R8 consumer rules。目标 App 仍需根据实际 Capability 合并
`INTERNET`、相机、定位等权限，并配置自身 application ID、正式公钥、
`minimumRelease`、签名证书和商店发布策略。

### 文件和打包

- Module Store 根目录使用内部 `noBackupFilesDir`，不要使用外部存储。
- 当前实现对模块和状态应用 `0600`。
- Offline Sealed 的 `module.pvm`、公钥和 bootstrap 可放入 APK 或 AAB 的受保护资源目录；APK 用于直接安装/测试/部分企业分发，AAB 用于 Google Play 生成设备 APK。
- 生产 Release 开启 R8 全量优化；AAR consumer rules 会保留 JNI native callback、
  `PvmModuleValidator` 和通过名称查找的 `PvmCrypto.verify`。
- NDK 产物是包含完整 Runtime 的 `libpvm_android.so`。
- NDK 28 产物的 ELF `PT_LOAD` 对齐为 16 KiB；门禁同时校验 ELF program header
  和 APK ZIP alignment，不能只依赖 `zipalign`。
- Capability manifest 生成的权限必须在打包时合并，远程模块不能新增权限。

`make delivery-matrix` 仍然只生成目标工程所需的嵌入输入，并在
`bootstrap.json.packageFormats` 中声明 `["apk", "aab"]`。仓库新增的 Demo Gradle
工程会把这些输入封装成可安装测试 APK/AAB；真正的业务生产包仍必须由目标 App 使用
正式 application ID、variant、keystore 和发布签名构建。

## iOS

### 已提供

- `PVMRuntimeBridge.mm/.h`：ARC Objective-C++ 桥和 C ABI。
- `PVMModuleStore.swift`：actor Module Store。
- `PVMPlatformCrypto.swift`：CryptoKit Ed25519。
- `PVMUIKitRenderer.swift` 与 `PVMSwiftUIRenderer.swift`。
- `PVMCapabilityRegistry.swift` 与基础 Capability。
- `PVMHost.swift`：`@MainActor` 统一 Host、C ABI v3 绑定、事件与生命周期入口。
- [`Package.swift`](../Package.swift)：iOS 15 的 C++ Core、Objective-C++ Bridge 和 Swift
  Runtime 源码包。
- `PrivacyInfo.xcprivacy`：随 Swift Package Runtime target 打包的隐私清单基线。
- `demo/PVMRuntimeDemo.xcodeproj`：使用本地 Package 的 UIKit 示例 App，构建时嵌入
  iOS `offline_sealed` 签名模块、公钥和 bootstrap。

### 推荐交付 Profile

iOS 默认建议使用 `offline_sealed`：把签名 `.pvm` 和公钥作为目标 App 的审核包资源，
再通过 `PVMHost` 加载；Runtime/Bridge 始终随 App 静态交付，不从网络下载 Framework。

在线签名字节码是可选交付模式，不代表天然符合 App Store 政策。选择
`online_provisioned` 或 `store_on_demand` 前，必须按实际产品功能、模块能改变的行为、
审核材料和目标市场逐项评估
[Apple App Review Guidelines 2.5.2](https://developer.apple.com/app-store/review/guidelines/)。
签名、受限 DSL/VM 和 Profile 约束是安全控制，不是审核结论。

### 在线模式的 Module Store 配置

以下配置只适用于产品已决定并审核在线模块交付的场景：

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

let store = try PVMModuleStore(configuration: configuration) { module, floor in
    try PVMHost.validateModule(
        module: module,
        publicKey: publicKeyURL,
        applicationID: Bundle.main.bundleIdentifier!,
        channel: "production",
        profile: "online_provisioned",
        minimumRelease: floor
    )
}
```

`PVMHost.validateModule` 通过 Objective-C++ Bridge/C ABI v3 预加载临时模块并返回模块
release；Store 会要求该值与 Manifest 完全一致。

Store 拒绝重定向，按流式大小上限读取响应，并在任何切换前完成 Manifest、Hash、模块
签名、五项绑定和 Runtime 预加载。`current.json` 与 Android/HarmonyOS 使用相同的
严格 LKG state 语义，损坏或其他 App/渠道/Profile 的状态不会被复用。

### 线程和生命周期

- `PVMModuleStore` 是 actor，网络和缓存状态串行化。
- `PVMHost`、UIKit/SwiftUI Renderer 在 MainActor 应用 UI Tree。
- Objective-C++ Bridge 持有 `pvm_runtime*`，异步 completion 回到宿主串行上下文后再恢复 VM。
- 页面退出、场景关闭或模块替换前调用任务取消；cancel/close 后到达的 completion 被
  generation/closed guard 丢弃。
- `appear` 只在节点 absent→present 时发送；整树重绘中仍存在的同 ID 节点不会重复发送。

### 构建和运行 iOS Demo

[`client/platform/ios/demo/PVMRuntimeDemo.xcodeproj`](../client/platform/ios/demo/PVMRuntimeDemo.xcodeproj)
可以直接由 Xcode 打开。命令行入口为：

```bash
make ios-demo-check
make ios-demo-run
```

`ios-demo-check` 使用本地 `PVMRuntime` Swift Package 构建 arm64 Simulator App，检查
ad-hoc 签名、iOS 15 deployment target、Privacy Manifest，以及 App 内
`bootstrap.json`、公钥和 `.pvm` 与交付矩阵完全一致。`ios-demo-run` 要求恰好有一个
已启动 Simulator；它安装并运行 `com.example.protected`，不会生成 IPA。

需要复现项目首页的验证状态和截图时执行：

```bash
make ios-demo-screenshot
```

该命令只卸载/重装这个 Demo，随后通过真实 UIKit 事件把 Counter 推进到
`count=2 / Status=Not set / Alice`，并将 Simulator 原始截图写入
`docs/assets/ios-demo.png`。当前证据来自 iPhone 17 Pro Max Simulator（iOS 26.2），
不应描述成 iPhone 真机、Archive 或 App Store 结果。

### 构建和验证 iOS SDK

在安装完整 Xcode 的 macOS 上，从仓库根目录执行：

```bash
make ios-sdk-check
```

该命令生成：

```text
dist/ios/PVMRuntime.xcframework
```

XCFramework 包含 Swift Host、UIKit/SwiftUI Renderer、CryptoKit、Objective-C++
Bridge 与完整 C++17 Runtime，含 arm64 iPhoneOS slice 和 arm64/x86_64 Simulator
slice，最低 iOS 15。门禁检查：

1. slice、架构、deployment target、稳定 Swift Interface 和完整 Runtime 符号。
2. 产物不包含私钥、模块或开发机绝对路径。
3. 全部 Swift 源在 Swift 6 complete strict-concurrency 下以 warning-as-error 构建。
4. 一个 Swift consumer 实际链接二进制 Simulator XCFramework。

这是 SDK 构建门禁，本身不生成 `.xcarchive` 或 IPA。示例 App 由独立
`make ios-demo-check` 构建并进行 Simulator ad-hoc codesign；两项门禁都不能替代
物理设备生命周期、Apple Distribution codesign、entitlement、隐私问卷或 App Store
审核。

### 在目标 App 中引入预编译 iOS SDK

下载并解压 `PVMRuntimeBinaryPackage-0.5.0.zip`，在 Xcode 中选择
**File → Add Package Dependencies → Add Local**，选择解压后的
`PVMRuntimeBinaryPackage` 目录。产品名为 `PVMRuntime`：

```swift
import PVMRuntime
```

也可以直接把 `PVMRuntime.xcframework` 加入目标的
**Frameworks, Libraries, and Embedded Content** 并选择 **Embed & Sign**。
两种方式都只链接预编译 Swift/Objective-C++/C++ 代码，不编译 PVM Runtime 源码。

### 文件和打包

- 模块使用 `completeUntilFirstUserAuthentication`。
- 状态文件使用完整文件保护和原子写。
- `make ios-sdk-check` 生成完整二进制 XCFramework；目标 App 负责嵌入、签名并完成
  archive/codesign。
- Demo 展示源码 Package 接入；它使用开发模块和 Simulator ad-hoc 签名，不是生产模板
  中的证书、Bundle ID 或发布身份。
- CryptoKit 验证内置 X.509 SubjectPublicKeyInfo Ed25519 公钥。
- Capability 生成的 Usage Description/entitlement 必须进入 App 审核产物。

## HarmonyOS

### 已提供

- DevEco Studio 6.1.1/API 24 工程，`compatibleSdkVersion` 为 API 23。
- `runtime` HAR：ArkTS Host、ArkUI Renderer、CryptoFramework Ed25519 verifier、
  状态生命周期和完整 C++17 VM。
- `demo` HAP：Offline Sealed Counter，内嵌平台/Profile 绑定的模块、公钥和 bootstrap。
- `pvm_napi.cpp`：标准 Node-API 桥，随 HAR/HAP 构建 arm64-v8a 与 x86_64。
- `PvmRuntimeHost.ets`：ArkTS Runtime/Capability Host。
- `PvmModuleStore.ets`：线上 Manifest、缓存与 LKG 参考实现。
- `PvmRuntimeSession.ets` / `PvmRuntimeTree.ets`：状态恢复、原生 ArkUI 递归渲染和事件回传。
- `installBasicHarmonyCapabilities`：`ui.toast` 与 `storage.kv` 基础 Adapter。

执行：

```bash
make harmony-sdk-check
```

目标 App 把预编译 HAR 复制到 `entry/libs/`，并在 `entry/oh-package.json5` 声明：

```json5
{
  "dependencies": {
    "@pvm/runtime": "file:./libs/pvm-runtime-0.5.0.har"
  }
}
```

执行 `ohpm install` 后直接引入：

```typescript
import { PvmRuntimeSession, PvmRuntimeTree } from '@pvm/runtime'
```

会构建并检查 `dist/harmony/pvm-runtime-0.5.0.har` 和
`dist/harmony/PVMRuntime-demo-unsigned.hap`。后者是 Emulator/开发联调产物，不具备
华为商业真机或应用市场要求的正式签名。

Demo 的 UI 不是静态 ArkUI Mock：原生控件事件经 Node-API 进入同一套 C++17 VM，
再由整批 UI Tree 驱动 ArkUI 重绘。除 DevEco 编译与 HAR/HAP 产物外，当前还使用
Huawei debug signed HAP 在 USB 目标 `3RM0224B30000105`、HUAWEI Pura 70 ADY-AL10
（HarmonyOS 6.1、API 23 兼容）运行真实 Offline Sealed 模块。自动交互验证了 count
`0 → 1 → 2`、异步 `Status: Not set`、输入 `Alice`，以及 Home、force-stop 和
重启后的状态恢复，原始截图为 `docs/assets/harmony-demo.png`。

物理设备运行必须显式提供目标与已签名 HAP，脚本会验证包签名和仓库 Demo 身份：

```bash
HARMONY_DEVICE_TARGET=3RM0224B30000105 \
HARMONY_SIGNED_HAP=/path/to/huawei-debug-signed.hap \
make harmony-device-run
```

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

- ArkTS Host 把 UI 批次交给项目注入的 ArkUI Renderer/Node Factory。
- Node-API 回调和 VM 生命周期必须在宿主选定的串行上下文中使用。
- Runtime HAR 的模块验签由 Harmony CryptoFramework Ed25519 verifier 实现；线上
  Module Store 仍需目标 App 注入文件、传输、Validator 与 Manifest 验签边界。
- HUKS 可保护缓存密钥；HAP/HSP/远程资源策略仍由 Profile 与发布流水线约束。

Pura 70 结果是一台 API 23 兼容物理设备的纵向 smoke，不代表完整设备矩阵或生产发布。
目标团队仍需完成 commercial/release/AppGallery 签名 HAP、HUKS、线上 Module
Store、完整 Capability，以及更多设备的生命周期、性能和设备实验室验收。

## KMP/CMP 与 Kuikly 边界

`client/platform/kmp` 现在提供可发布的 `commonMain` API：`PvmRuntimePort`、
`PvmRuntimeClient`、启动绑定、事件和快照模型。`make kmp-check` 会编译 JVM 与 iOS
Simulator ARM64 并运行生命周期测试，`make kmp-packages` 生成
`com.protectedvm:pvm-runtime-kmp:0.5.0` Maven 变体。

`compose/PvmComposeRenderer.kt` 和 `platform/kuikly/PvmKuiklyRenderer.kt` 仍是中立树
与事件 Port；它们没有锁定具体 Compose Multiplatform/Kuikly SDK 版本。因此公共
KMP API 已可分发，但目标 UI 框架 Adapter 仍必须在产品选型后编译和真机验证。

产品确实需要 KMP/CMP 时，应分别复用现有 Android 和 iOS Runtime，不新增虚构的
`kmp` 字节码平台；只有需要 Kuikly 的产品才应锁定具体版本并实现、编译和真机验证
Adapter。

## C ABI 生命周期

新移动端集成使用 v3 创建接口；回调结构仍名为 `pvm_host_callbacks_v2`：

1. 安装 `pvm_host_callbacks_v2`，包括签名验证回调。
2. 调用 `pvm_runtime_create_v3`，传入预期 application/channel/platform/profile 和
   `minimum_release`，完成模块签名、绑定、防回滚和字节码验证。
3. 读取 Runtime metadata，并让 Capability Registry 检查最低版本。
4. 可选调用 `pvm_runtime_restore_state`。
5. 调用 `pvm_runtime_start`。
6. tap/appear 等无值事件调用 `pvm_runtime_dispatch`；Input/Switch 的
   change/submit 调用 `pvm_runtime_dispatch_value`。
7. 异步结果调用 `pvm_runtime_complete_effect`。
8. 生命周期结束调用 `pvm_runtime_cancel_all_tasks`。
9. 两次调用 `pvm_runtime_snapshot_state` 获取长度和内容，并原子持久化。
10. 调用 `pvm_runtime_destroy`。

Runtime 只能 start 一次；dispatch/complete 在 start 前失败，restore 在 start 后失败。
cancel 会删除所有 continuation，之后直接调用 C ABI 完成同一 task 会返回
“missing or cancelled”；平台 Host 还会在边界丢弃 cancel/close 后的迟到回调。

旧的 `pvm_runtime_create` 和 `pvm_runtime_create_v2` 只为 ABI 兼容保留，未接收完整
channel/platform/profile 预期值，不应用于新的移动端接入。

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
- `appear` 按 absent→present 触发：同 ID 节点连续存在于 replace 批次时只发一次，
  从树中移除再加入后才能再次触发。
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
