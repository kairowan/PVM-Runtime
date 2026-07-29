# 功能完成度

这份清单按“能够在当前仓库运行”统计，不把类型声明、接口占位或目标 App 需要实现的
Adapter 算作完成。平台编译只能证明源码与当前 SDK/头文件相容，不能替代真机验收；
Android 已额外完成一台 HONOR API 35 设备的交互与状态恢复验收。

## 核心链路

| 功能 | 状态 | 可运行证据 |
|---|---|---|
| DSL 静态类型、控制流与预算检查 | 已实现 | `make test` |
| PVBC v1–v5 读取、签名、绑定、防回滚 | 已实现 | `make test compatibility` |
| 同步/异步 Effect 与取消 | 已实现 | C ABI smoke、任务预算测试 |
| v4 稳定状态 ID 与增量迁移 | 已实现 | 状态改名/新增/冲突测试 |
| v5 Input/Switch 事件值进入 VM 状态 | 已实现 | `event.value` C ABI 回归测试 |
| 签名 Manifest、下载、Hash、预加载、原子 LKG | 已实现 | HTTP/LKG 测试与三端 Module Store |
| Android Gradle SDK 与 Demo | 已实现 | `make android-demo-check` |
| Android Debug APK/AAB | 已生成 | `dist/android/PVMRuntime-demo-debug.{apk,aab}` |
| Android Release AAR/本地 Maven | 已生成 | `com.protectedvm:pvm-runtime:0.5.0` |
| 生产签名 APK/AAB、IPA、HAP | 目标工程负责 | 仍需正式身份、证书和商店配置 |

## Android 产品化基线

| 项目 | 当前状态 | 验收边界 |
|---|---|---|
| Gradle 工程 | `:runtime` Android Library 与 `:demo` Application 已可独立构建 | Gradle Wrapper 8.13 |
| 编译工具链 | compile/target API 36，NDK `28.0.13004108` | Runtime minSdk 24；Demo minSdk 33 |
| Native ABI | `arm64-v8a`、`x86_64` | AAR、APK、AAB 均检查包含完整 VM |
| 16 KiB 页面 | ELF `PT_LOAD` 对齐不小于 16 KiB，APK 使用 16 KiB zipalign 检查 | `scripts/check_android_artifacts.py` |
| SDK 分发 | Release AAR 与本地 Maven 仓库 | `com.protectedvm:pvm-runtime:0.5.0` |
| Demo 交付 | Debug APK、Debug AAB | 开发签名/调试产物，不是生产发布包 |
| R8 | 非 debuggable 的 minified smoke APK | 使用测试签名；HONOR API 35 启动、交互和状态恢复通过 |
| 包完整性 | 模块、公钥、bootstrap、双 ABI、签名、篡改拒绝自动检查 | `make android-demo-check` |
| 真机 | HONOR BRP-AN00、Android API 35 完成交互与状态恢复 | 单机型 smoke，不代表完整设备矩阵 |

## Renderer

| 后端 | 当前可用范围 | 仍需处理 |
|---|---|---|
| Android View | 11 类节点、属性、tap/change/submit/appear、输入值、NativeSurface 工厂；HONOR API 35 已验收交互/状态恢复 | 图片加载策略、更多 API/厂商设备、样式与性能 |
| Android Compose/CMP | 递归树与输入值参考实现 | 接入 Compose 依赖；完善 Switch 视觉、submit/appear 和测试 |
| UIKit | 11 类节点、Stack 约束、属性、四类事件、输入值、NativeSurface 工厂 | 图片加载、复杂布局/复用与真机校准 |
| SwiftUI | 递归树、输入绑定、Switch、tap/appear/submit、enabled/无障碍 | NativeSurface 仍是占位；图片与复杂列表策略 |
| ArkUI | 中立树到工厂的完整事件值合同 | 需要 DevEco SDK 和业务 `ArkUiNodeFactory` |
| Kuikly | 中立树、属性、事件值 Port 合同 | 需要选定 Kuikly 版本并实现/编译 Port |

`spec/renderer_conformance.json` 中的 `compiled`、`sdk-required` 和
`adapter-required` 是机器可读后端状态。

## Capability

`spec/host_idl.json` 定义 27 个 Capability；定义合同不代表三端已经安装实现。

| 宿主 | 仓库内具体 Adapter |
|---|---|
| Android | `ui.toast`、`storage.kv`、`network.http`、`push.inbox`、`permission.request` |
| iOS | `ui.toast`、`storage.kv`、`network.http`、`push.inbox` |
| HarmonyOS | Registry/策略边界已实现；具体系统 Adapter 未实现 |

以下能力当前只有版本化合同，必须由目标 App/供应商 SDK 实现后才能使用：

`background.task`、`biometric.auth`、`bluetooth.scan`、`camera.capture`、
`clipboard.system`、`database.scoped`、`deeplink.open`、`file.scoped`、
`location.current`、`map.control`、`media.player`、`microphone.capture`、
`network.transfer`、`network.websocket`、`nfc.scan`、`notification.post`、
`payment.purchase`、`qr.scan`、`secure.keystore`、`share.system`、
`system.extension` 和 `telemetry.event`。

Native Component `camera.preview`、`host.screen`、`map.view` 和 `player.view`
同样是合同，需要通过各 Renderer 的 NativeSurface 工厂接入。

## 剩余跨平台五阶段

Android 已从“桥接源码”推进到可构建、可分发 SDK 和单设备 Demo 基线。剩余工作按最小
依赖顺序拆为五阶段：

1. **共享边界加固**：让 Runtime 创建接口强制校验目标平台；修复 iOS/HarmonyOS
   Module Store 的重定向、大小、LKG 状态边界；统一关闭后异步 completion 与
   `appear` 生命周期语义，并补负向回归。
2. **iOS 产品 SDK**：构建并链接完整 C++ Runtime 的静态 XCFramework，提供 Swift
   Package、`@MainActor PVMHost`、UIKit/SwiftUI 示例 App，以及设备/模拟器构建门禁。
3. **HarmonyOS 产品 SDK**：建立真实 DevEco 工程和 HAR/HSP 分发物，实现文件、网络、
   HUKS/验签、Validator、基础 Capability 与 ArkUI 节点，并生成示例 HAP。
4. **KMP/CMP 与 Kuikly**：建立 `commonMain/androidMain/iosMain`、平台 actual Runtime、
   可接入 Host 的 Compose Renderer 和 Maven 发布；锁定 Kuikly 版本并实现独立 Adapter。
   KMP/Kuikly Android target 使用 Android 模块，iOS target 使用 iOS 模块，不新增虚构的
   `kmp` 字节码平台。
5. **生产验收与运营**：为 Android/iOS/HarmonyOS 生成正式签名 APK/AAB、IPA、HAP，
   完成三端真机矩阵、业务所需 Capability、HSM/KMS、生产鉴权、审计、告警、性能、
   商店与支付沙箱证据。

完整外部验收项见[交付状态](DELIVERY_STATUS.md)，接入步骤见[三端集成](PLATFORM_INTEGRATION.md)。
