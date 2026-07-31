[English](FUNCTIONAL_STATUS.md)

# 功能完成度

这份清单按“能够在当前仓库运行”统计，不把类型声明、接口占位或目标 App 需要实现的
Adapter 算作完成。平台编译只能证明源码与当前 SDK/头文件相容，不能替代真机验收；
Android 已额外完成一台 HONOR API 35 设备的交互与状态恢复验收；iOS 已完成 iOS 26.2
Simulator 的等价业务交互与截图，但这不是物理设备证据。HarmonyOS 已经由 DevEco
API 24 真实构建兼容 API 23 的 HAR 与 unsigned Emulator HAP，并使用 Huawei debug
signed HAP 在 HUAWEI Pura 70 ADY-AL10（HarmonyOS 6.1、API 23 兼容）完成真实 Offline
Sealed 模块交互、状态恢复和截图；这仍不是商业发布签名或完整设备矩阵。

## 核心链路

| 功能 | 状态 | 可运行证据 |
|---|---|---|
| DSL 静态类型、控制流与预算检查 | 已实现 | `make test` |
| PVBC v1–v5 读取、签名、绑定、防回滚 | 已实现 | `make test compatibility` |
| C ABI v4 五项绑定与 UI Wire v2 补丁 | 已实现 | v1/v3 兼容、v4 补丁 C ABI smoke 与三端 Host 构建 |
| Runtime 创建/恢复/单次启动/分发/取消生命周期 | 已实现 | C ABI 生命周期负向测试 |
| 同步/异步 Effect 与取消 | 已实现 | C ABI smoke、任务预算测试 |
| 节点 revision、精确 changed 清单与结构回退 | 已实现 | C ABI smoke、Android 真机、iOS Simulator 与 Harmony Host 差量/性能门禁 |
| v4 稳定状态 ID 与增量迁移 | 已实现 | 状态改名/新增/冲突测试 |
| v5 Input/Switch 事件值进入 VM 状态 | 已实现 | `event.value` C ABI 回归测试 |
| 签名 Manifest、下载、Hash、预加载、原子 LKG | 已实现 | HTTP/LKG 测试与三端 Module Store |
| 三端 LKG state 绑定与严格历史校验 | 已实现 | `make test platform-check`（desktop 负向回归 + 三端边界编译） |
| Android Gradle SDK 与 Demo | 已实现 | `make android-demo-check` |
| Android Debug APK/AAB | 已生成 | `dist/android/PVMRuntime-demo-debug.{apk,aab}` |
| Android Release AAR/本地 Maven | 已生成 | `com.protectedvm:pvm-runtime:0.6.0` |
| iOS Swift Package、统一 Host、Privacy Manifest | 已实现 | `make ios-sdk-check` |
| iOS 完整二进制 XCFramework | 可重复生成 | `dist/ios/PVMRuntime.xcframework` |
| iOS Xcode Demo | 已实现 | `make ios-demo-check` 与 iOS 26.2 Simulator 截图 |
| HarmonyOS DevEco Runtime SDK | 已实现 | `make harmony-sdk-check` 构建 HAR、unsigned HAP 与双 ABI |
| HarmonyOS 真机 Demo 交互 | 已验证 | Pura 70 上验证 count 0→1→2、异步存储、Alice 输入、Home/force-stop 重启恢复与截图 |
| KMP 公共 SDK | 已实现 | `make kmp-check` 编译 commonMain/JVM/iOS Simulator ARM64 并运行生命周期测试 |
| KMP Maven 制品 | 可重复生成 | `make kmp-packages`，坐标 `com.protectedvm:pvm-runtime-kmp:0.6.0` |
| 三端预编译 SDK Release 集合 | 已实现 | `make sdk-release-assets` 生成 AAR/Maven、Binary Swift Package/XCFramework、HAR 与校验清单 |
| 生产签名 APK/AAB、IPA、HAP | 目标工程负责 | 仍需正式身份、证书和商店配置 |

## Android 产品化基线

| 项目 | 当前状态 | 验收边界 |
|---|---|---|
| Gradle 工程 | `:runtime` Android Library 与 `:demo` Application 已可独立构建 | Gradle 9.6.1、AGP 9.3.1、内置 Kotlin 2.4.10 |
| 编译工具链 | compile/target API 36，NDK `28.0.13004108` | Runtime minSdk 24；Demo minSdk 33 |
| Native ABI | `arm64-v8a`、`x86_64` | AAR、APK、AAB 均检查包含完整 VM |
| 16 KiB 页面 | ELF `PT_LOAD` 对齐不小于 16 KiB，APK 使用 16 KiB zipalign 检查 | `scripts/check_android_artifacts.py` |
| SDK 分发 | Release AAR 与本地 Maven 仓库 | `com.protectedvm:pvm-runtime:0.6.0` |
| Demo 交付 | Debug APK、Debug AAB | 开发签名/调试产物，不是生产发布包 |
| R8 | 非 debuggable 的 minified smoke APK | 使用测试签名；HONOR API 35 启动、交互和状态恢复通过 |
| 包完整性 | 模块、公钥、bootstrap、双 ABI、签名、篡改拒绝自动检查 | `make android-demo-check` |
| 真机 | HONOR BRP-AN00、Android API 35 完成交互与状态恢复 | 单机型 smoke，不代表完整设备矩阵 |

## Renderer

| 后端 | 当前可用范围 | 仍需处理 |
|---|---|---|
| Android View | 11 类节点、精确 `changed` 按 ID 提交、稳定 ID 控件复用、`RecyclerView + ListAdapter/DiffUtil`、大批次后台解析/最新批次背压、输入值、NativeSurface 和 appear；HONOR API 35 上 1000 行只挂载可见项，240 节点单叶子更新 p95 为 172–187 μs、比配对全量重绑低约 35%–39% | Release Macrobenchmark/滚动帧与内存 SLO、图片策略、更多 API/厂商设备与产品样式 |
| Android Compose/CMP | KMP 公共调用层已进入独立 Gradle 构建；递归 Compose Tree 仍是 Port | 锁定目标 Compose 版本、连接平台 Host 并做 UI/真机测试 |
| UIKit | 11 类节点、Wire v2 精确 `changed` 按 ID 提交、稳定 ID 控件复用、`UICollectionView` Compositional List 与 Diffable Data Source、大批次后台解析/背压、输入值、NativeSurface 和 appear；240 节点 Simulator 补丁提交 p95 7 μs | iOS 真机大列表/Instruments SLO、图片与产品复杂布局 |
| SwiftUI | `node.id + revision` Equatable 子树门、Wire v2 稳定路径祖先合并、原生惰性 `List`、大批次后台解析/背压、输入绑定、Switch、事件和无障碍；240 节点 Simulator 补丁合并 p95 6 μs | NativeSurface 仍是占位；真机 Instruments、图片与产品样式 |
| ArkUI | DevEco API 24 原生树、Wire v2 稳定 ID/路径索引精确更新、32 KiB `taskpool` 解析与最新批次背压、`List + Repeat.virtualScroll(reusable: true)`、事件值和 appear；Pura 70 已完成 Counter 交互、状态恢复与截图 | 大列表真机性能 SLO、NativeSurface 业务工厂与更多设备 |
| Kuikly | 未进入构建、未锁定 SDK 版本的 Port 原型 | 仅在产品需要时选定版本并实现/编译/真机验证 |

`spec/renderer_conformance.json` 中的 `compiled`、`sdk-required` 和
`adapter-required` 是机器可读后端状态。

## Capability

`spec/host_idl.json` 定义 27 个 Capability；定义合同不代表三端已经安装实现。

| 宿主 | 仓库内具体 Adapter |
|---|---|
| Android | `ui.toast`、`storage.kv`、`network.http`、`push.inbox`、`permission.request` |
| iOS | `ui.toast`、`storage.kv`、`network.http`、`push.inbox` |
| HarmonyOS | `ui.toast`、`storage.kv` 基础 Adapter；其余系统 Adapter 未实现 |

以下能力当前只有版本化合同，必须由目标 App/供应商 SDK 实现后才能使用：

`background.task`、`biometric.auth`、`bluetooth.scan`、`camera.capture`、
`clipboard.system`、`database.scoped`、`deeplink.open`、`file.scoped`、
`location.current`、`map.control`、`media.player`、`microphone.capture`、
`network.transfer`、`network.websocket`、`nfc.scan`、`notification.post`、
`payment.purchase`、`qr.scan`、`secure.keystore`、`share.system`、
`system.extension` 和 `telemetry.event`。

Native Component `camera.preview`、`host.screen`、`map.view` 和 `player.view`
同样是合同，需要通过各 Renderer 的 NativeSurface 工厂接入。

## 当前状态与剩余三个核心阶段

以下两项基线已经完成，不再列入“剩余阶段”：

- **共享边界**：C ABI v4 强绑定与 Wire v2、Runtime 生命周期状态机、三端严格 LKG state、
  cancel/close 迟到回调丢弃、Renderer `appear` absent→present 与负向回归已落地。
- **iOS SDK 基线**：Swift Package、`@MainActor PVMHost`、Privacy Manifest、完整 C++17
  Runtime 完整二进制 XCFramework、Xcode Demo、`make ios-sdk-check` 和 `make ios-demo-check`
  已落地。尚未完成的是物理设备生命周期、archive/Apple Distribution codesign、
  entitlement 和审核证据；这些进入生产验收阶段。

剩余工作按依赖关系收束为三个核心阶段：

1. **HarmonyOS 产品化补齐**：DevEco API 24 工程、兼容 API 23 的 Runtime HAR、
   arm64-v8a/x86_64 C++17 Node-API、ArkUI Renderer、两项基础 Capability 和
   unsigned Emulator HAP 已完成构建，Huawei debug signed HAP 已在一台 Pura 70
   完成交互、状态恢复与截图；仍需 HUKS、线上 Module Store、完整 Capability、
   commercial/release/AppGallery 签名 HAP 和更多物理设备实验室证据。
2. **KMP/CMP 产品化（Kuikly 按需）**：`commonMain` 生命周期/事件 API、JVM/iOS
   Kotlin/Native 编译、测试和 Maven 分发已完成；仍需根据目标 App 建立平台 actual
   Runtime 与 Compose Host。只有业务明确采用 Kuikly 时才锁定版本并实现独立 Adapter。
   Android/iOS target 复用现有平台模块，不新增虚构的 `kmp` 字节码平台。
3. **生产验收与运营**：完成 iOS 真机/发布签名，为三端生成正式签名 APK/AAB、IPA、
   HAP，补齐完整设备矩阵、业务 Capability、HSM/KMS、生产鉴权、审计、告警、性能、
   商店与支付沙箱证据。iOS 在线字节码交付还必须按具体产品评估 Apple 2.5.2，不能
   将本 SDK 描述为天然合规。

完整外部验收项见[交付状态](DELIVERY_STATUS.zh-CN.md)，接入步骤见[三端集成](PLATFORM_INTEGRATION.zh-CN.md)。
