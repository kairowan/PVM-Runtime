# 交付状态与验收证据

本页区分三种状态：

- **仓库已实现**：存在实际代码与可运行路径。
- **自动化已证明**：存在可重复门禁，当前环境已通过。
- **外部待验收**：必须使用组织账号、生产基础设施、商业 SDK 或物理设备取得证据。

“工程基线完成”不等于“产品已获商店、安全或生产认证”。

## 当前版本快照

| 项目 | 当前状态 |
|---|---|
| 项目名 | PVM Runtime |
| Runtime | 5 |
| 默认字节码 | PVBC v5 |
| 历史读取 | PVBC v1–v5 |
| 模块签名 | Ed25519 / PVMP v1 |
| Manifest | Ed25519 签名信封 v1 |
| 平台 | Android、iOS、HarmonyOS；desktop 参考 Host |
| Delivery Profile | 4 |
| 自动交付矩阵 | 3 平台 × 4 Profile = 12 套宿主嵌入输入 |
| Android 目标包格式 | APK、AAB（由目标 Gradle 工程最终打包） |
| 历史兼容矩阵 | 5 业务域 × PVBC v1/v2/v3 = 15 |

## 仓库能力状态

| 领域 | 仓库已实现 | 自动化证据 | 外部缺口 |
|---|---|---|---|
| DSL/编译器 | 状态、页面、处理器、Effect、输入事件值、Profile/IDL/预算检查 | `make test verify-contracts` | 完整语言愿景、IDE、真实业务规模 |
| 模块安全 | 确定性 PVBC、Ed25519、绑定、防回滚、验证器 | `make test fuzz-check sanitizer-check` | 长时 fuzz、独立安全审计 |
| 状态演进 | v4 稳定 ID、改名/新增迁移、类型冲突拒绝 | 状态迁移端到端测试 | 大版本业务迁移工具链 |
| 发布服务 | 内容寻址、访问策略、签名 Manifest、ETag、灰度、审计 | HTTP/篡改/灰度/LKG 测试 | 生产 CDN、数据库、鉴权 HA |
| Android | Kotlin/JNI/View、输入值回传、Module Store、完整 NDK `.so` | `make platform-check` | Compose/CMP 目标依赖、目标 App、API/真机与商业 SDK |
| iOS | Objective-C++/Swift/UIKit/SwiftUI、输入值回传、CryptoKit Store | `make platform-check` | NativeSurface 工厂、XCFramework、真机、商店审核 |
| HarmonyOS | Node-API/ArkTS/ArkUI 合同与 Module Store | 可移植 C++/合同检查 | DevEco HAP、HUKS Adapter、真机 |
| Capability | 27 项版本化合同；Android 5 项、iOS 4 项基础 Adapter | `make verify-contracts platform-check` | Harmony 具体 Adapter；其余供应商/系统能力 |
| Delivery | 四 Profile 与 12 套宿主嵌入输入；Android 声明 APK/AAB | `make delivery-matrix` | 目标 App 最终 APK/AAB/IPA/HAP、各商店/MDM 上传和审批 |
| 兼容性 | v1–v5 Runtime 读取、五域历史矩阵 | `make compatibility test` | 真实流量、长期升级数据 |

## 原计划时间段映射

仓库把原 0–36 个月方案压缩为一条可执行工程基线：

| 时间段 | 仓库内交付 | 可执行验收 | 仍需外部证据 |
|---|---|---|---|
| 4–9 个月 | 三端 Host、平台验签、Native Renderer、LKG、四 Profile | `make platform-check delivery-matrix` | DevEco 完整构建、三端真机、推送账号 |
| 10–18 个月 | Host/组件 IDL、六类 Renderer 接口、重能力合同 | `make verify-contracts` | 各 SDK Adapter 与沙箱凭证 |
| 19–27 个月 | 远程 signer、签名 Manifest、防回滚、灰度、审计和门禁 | `make test sanitizer-check fuzz-check` | 正式 KMS/HSM、商店审核、红队 |
| 28–36 个月 | 五业务域历史兼容矩阵与交付治理 | `make compatibility release-check` | 真实业务流量、性能 SLO、升级演练 |

## 自动化门禁

[`spec/release_gates.json`](../spec/release_gates.json) 是机器可读来源。

| ID | 命令 | 证明范围 |
|---|---|---|
| `core-e2e` | `make test` | 编译、执行、C ABI、篡改、状态、HTTP、灰度 |
| `host-builds` | `make platform-check` | 三端 Host 当前环境可验证部分 |
| `host-idl` | `make generate-host-idl` | 生成接口与 IDL 一致 |
| `documentation` | `make docs-check` | README/docs 本地链接和 SVG 完整性 |
| `delivery-profiles` | `make delivery-matrix` | 12 套 Profile 产物 |
| `historical-bytecode` | `make compatibility` | 15 项历史模块升级 |
| `sanitizers` | `make sanitizer-check` | Linux ASan+UBSan / macOS UBSan |
| `package-fuzz-smoke` | `make fuzz-check` | 包解析覆盖引导 smoke |

统一入口：

```bash
make release-check
```

macOS 26 的 Apple ASan runtime 当前会在 dyld 初始化阶段自旋，因此本机门禁使用 UBSan；Linux CI 仍配置 ASan+UBSan。该限制已写在 CMake 中，不能把 macOS UBSan 描述成已经运行 ASan。

## 外部必需证据

这些项目不能由本仓库自动生成通过结果：

| ID | 所需证据 | 建议负责人 |
|---|---|---|
| `hsm-production-key` | KMS/HSM key ID、访问策略、轮换演练和审计导出 | 安全/平台 |
| `store-policy-review` | Google Play、Apple、Huawei 对精确 Profile/版本的审核记录 | 发布/法务 |
| `device-lab` | 三端物理设备的生命周期、相机、媒体、推送和后台结果 | QA/平台 |
| `billing-sandboxes` | Play Billing、StoreKit、Huawei IAP、企业支付回执 | 支付团队 |
| `red-team` | 黑盒、Root/Jailbreak、Hook 和部分源码泄露报告 | 安全团队 |

此外建议归档：

- 生产 TLS/鉴权/CDN 高可用演练。
- P50/P95/P99 验证、冷启动、页面切换与内存指标。
- 一次完整 release 递增、10% 灰度、止血和更高 release 业务回退演练。
- 缓存损坏、Manifest 服务中断和 signer 不可用的恢复记录。

## 防回滚验收语义

`pvm_server.release --rollback` 把 rollout 降到 0%，只阻止更多设备升级。已经接受新 release 的设备继续使用本地 LKG，不会接受更小 release。

业务必须回退时：

```text
旧业务逻辑 + 更高 release + 新签名发布
```

下列做法都应判定验收失败：

- 降低客户端 `minimumRelease`。
- 清空状态或 LKG 以强制加载旧模块。
- 覆盖已有 Hash URL 的模块正文。
- 临时返回未签名 Manifest。
- 绕过 VM 预加载验证直接切换。

## 下一阶段优先级

逐功能状态和未完成项见[功能完成度](FUNCTIONAL_STATUS.md)。

### P0：生产信任根

- 正式 signer/HSM。
- App 内置公钥与轮换策略。
- 生产鉴权、审计、告警和职责分离。

### P1：目标 App 集成

- 三端真实工程接入 Module Store、Renderer 和 Capability Registry。
- KeyStore/Keychain/HUKS 文件保护。
- 支付、地图、相机、媒体、推送 Adapter。

### P2：证据与规模

- DevEco 和三端真机矩阵。
- 应用商店/支付沙箱。
- 持续 fuzz、红队和供应链扫描。
- 真实模块体积、冷启动、帧预算和服务 SLO。

发布操作见[发布与运维](OPERATIONS.md)，威胁与控制见[安全模型](SECURITY_MODEL.md)。
