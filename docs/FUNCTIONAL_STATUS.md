# 功能完成度

这份清单按“能够在当前仓库运行”统计，不把类型声明、接口占位或目标 App 需要实现的
Adapter 算作完成。平台编译只能证明源码与当前 SDK/头文件相容，不能替代真机验收。

## 核心链路

| 功能 | 状态 | 可运行证据 |
|---|---|---|
| DSL 静态类型、控制流与预算检查 | 已实现 | `make test` |
| PVBC v1–v5 读取、签名、绑定、防回滚 | 已实现 | `make test compatibility` |
| 同步/异步 Effect 与取消 | 已实现 | C ABI smoke、任务预算测试 |
| v4 稳定状态 ID 与增量迁移 | 已实现 | 状态改名/新增/冲突测试 |
| v5 Input/Switch 事件值进入 VM 状态 | 已实现 | `event.value` C ABI 回归测试 |
| 签名 Manifest、下载、Hash、预加载、原子 LKG | 已实现 | HTTP/LKG 测试与三端 Module Store |
| 最终 APK/AAB/IPA/HAP | 目标工程负责 | 本仓库只生成嵌入输入 |

## Renderer

| 后端 | 当前可用范围 | 仍需处理 |
|---|---|---|
| Android View | 11 类节点、属性、tap/change/submit/appear、输入值、NativeSurface 工厂 | 图片加载策略、真机样式/性能 |
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

## 当前优先顺序

1. 在真实 Android/iOS/HarmonyOS App 工程生成并签名 APK/AAB、IPA、HAP。
2. 用业务实际需要选择 Capability Adapter；不要一次实现全部 27 项。
3. 完成 ArkUI/Kuikly/Compose 目标依赖编译与三端真机矩阵。
4. 接入正式 HSM/KMS、生产鉴权、审计、告警和商店/支付沙箱证据。

完整外部验收项见[交付状态](DELIVERY_STATUS.md)，接入步骤见[三端集成](PLATFORM_INTEGRATION.md)。
