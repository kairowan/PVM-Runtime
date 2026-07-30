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
| 新移动端 C ABI | v3：application/channel/platform/profile/release floor 强绑定 |
| 平台 | Android、iOS、HarmonyOS；desktop 参考 Host |
| Delivery Profile | 4 |
| 自动交付矩阵 | 3 平台 × 4 Profile = 12 套宿主嵌入输入 |
| Android Gradle 交付 | Debug APK/AAB、R8 smoke APK、Release AAR、本地 Maven |
| Android SDK 坐标 | `com.protectedvm:pvm-runtime:0.5.0` |
| Android 工具链 | compile/target API 36、NDK 28、双 ABI、16 KiB 对齐 |
| Android 真机 | HONOR BRP-AN00、API 35 交互与状态恢复通过 |
| iOS SDK 交付 | Swift Package、`@MainActor PVMHost`、Privacy Manifest、静态 XCFramework 门禁 |
| iOS XCFramework | `make ios-sdk-check` 生成 `dist/ios/PVMBridge.xcframework` |
| HarmonyOS 边界 | 仅可移植 Node-API/ArkTS 合同；本机无 DevEco，无 HAR/HAP |
| 生产包 | 正式签名 APK/AAB、IPA、HAP 仍由目标工程与发布账号生成 |
| 历史兼容矩阵 | 5 业务域 × PVBC v1/v2/v3 = 15 |

## 仓库能力状态

| 领域 | 仓库已实现 | 自动化证据 | 外部缺口 |
|---|---|---|---|
| DSL/编译器 | 状态、页面、处理器、Effect、输入事件值、Profile/IDL/预算检查 | `make test verify-contracts` | 完整语言愿景、IDE、真实业务规模 |
| 模块安全 | 确定性 PVBC、Ed25519、C ABI v3 五项绑定、防回滚、验证器 | `make test fuzz-check sanitizer-check` | 长时 fuzz、独立安全审计 |
| 状态演进 | v4 稳定 ID、改名/新增迁移、类型冲突拒绝 | 状态迁移端到端测试 | 大版本业务迁移工具链 |
| 发布服务 | 内容寻址、访问策略、签名 Manifest、ETag、灰度、审计 | HTTP/篡改/灰度/LKG 测试 | 生产 CDN、数据库、鉴权 HA |
| Android | Gradle Library/Demo、Kotlin/JNI/View、严格绑定的 Module Store、双 ABI `.so`、AAR/Maven、Debug APK/AAB、R8 smoke | `make platform-check android-demo-check`；HONOR API 35 人工真机验收 | Compose/CMP、更多设备/性能、业务 Capability、正式签名与商店 |
| iOS | Swift Package、Objective-C++/Swift、`PVMHost`、UIKit/SwiftUI、严格绑定的 CryptoKit Store、Privacy Manifest、静态 XCFramework | `make platform-check ios-sdk-check` | 示例 App、真机、archive/codesign、完整 NativeSurface、审核 |
| HarmonyOS | 可移植 Node-API/ArkTS/ArkUI 合同与严格绑定的 Module Store | 可移植 C++/合同检查 | DevEco HAR/HSP/HAP、HUKS Adapter、真机 |
| Capability | 27 项版本化合同；Android 5 项、iOS 4 项基础 Adapter | `make verify-contracts platform-check` | Harmony 具体 Adapter；其余供应商/系统能力 |
| Delivery | 四 Profile 与 12 套宿主嵌入输入；Android 有 Demo APK/AAB 和 SDK AAR/Maven；iOS 有 XCFramework 构建门禁 | `make delivery-matrix android-demo-check ios-sdk-check` | 正式签名三端安装包、各商店/MDM 上传和审批 |
| 兼容性 | v1–v5 Runtime 读取、五域历史矩阵 | `make compatibility test` | 真实流量、长期升级数据 |

## Android 本轮交付证据

| 证据 | 结果 | 说明 |
|---|---|---|
| Gradle Runtime | `:runtime:assembleRelease` 通过 | Release AAR 含 Kotlin Host 和完整 C++17 VM |
| Demo APK | `dist/android/PVMRuntime-demo-debug.apk` | Debug 签名，可直接安装测试 |
| Demo AAB | `dist/android/PVMRuntime-demo-debug.aab` | Debug Bundle，用于验证 AAB 打包内容 |
| R8 smoke | `dist/android/PVMRuntime-demo-minified-smoke.apk` | minified、非 debuggable，使用测试签名；真机启动/交互通过 |
| SDK AAR | `dist/android/pvm-runtime-0.5.0.aar` | `arm64-v8a` 与 `x86_64` |
| 本地 Maven | `dist/android/maven/` | 坐标 `com.protectedvm:pvm-runtime:0.5.0`，POM 保留 Tink 依赖 |
| API/NDK | compileSdk/targetSdk 36，NDK `28.0.13004108` | Demo minSdk 33；Runtime minSdk 24 |
| 16 KiB | APK/R8 APK zipalign 与 AAR 内 ELF `PT_LOAD` 检查通过 | 同时检查双 ABI |
| 离线资源 | APK/AAB/R8 APK 内嵌相同 module、公钥和 bootstrap | Hash、PVMP/Ed25519 结构及篡改拒绝通过 |
| 真机 | HONOR BRP-AN00、API 35 | 安装启动、业务交互、状态恢复已人工验证 |

Debug APK/AAB 与 R8 smoke APK 都是开发/测试构建；其中 APK 使用测试签名，不能作为
生产商店包。HONOR 结果是一台真实设备的纵向 smoke 证据，不替代 API、厂商、内存和
生命周期完整矩阵。

## iOS SDK 本轮交付证据

| 证据 | 结果 | 说明 |
|---|---|---|
| Swift Package | 根目录 `Package.swift` | iOS 15；C++ Core、Objective-C++ Bridge、Swift Runtime 三层 target |
| 统一 Host | `@MainActor PVMHost` | C ABI v3 绑定、Renderer/Capability、状态与关闭入口 |
| Privacy Manifest | `PrivacyInfo.xcprivacy` | Swift Runtime target 资源基线；目标 App 仍需按实际数据用途合并审核声明 |
| XCFramework | `dist/ios/PVMBridge.xcframework` | `make ios-sdk-check` 可重复生成，不等同 IPA |
| slice | arm64 iPhoneOS；arm64/x86_64 Simulator | iOS 15 静态库，完整链接 C++17 Runtime 与 Bridge |
| consumer | Swift 6 complete strict-concurrency + 实际链接 probe | warnings-as-errors，并检查无未解析 PVM 符号 |
| 产物安全 | 自动扫描公开头、私钥/模块后缀和本机绝对路径 | 不替代独立安全审计 |

当前 iOS 门禁不生成示例 App、`.xcarchive` 或 IPA，不执行 codesign、真机生命周期、
entitlement、隐私问卷或 App Store 审核。默认建议 `offline_sealed`；在线字节码交付
必须按实际产品评估
[Apple App Review Guidelines 2.5.2](https://developer.apple.com/app-store/review/guidelines/)，
不能因为模块有签名或 VM 受限就宣称天然合规。

## 原计划时间段映射

仓库把原 0–36 个月方案压缩为一条可执行工程基线：

| 时间段 | 仓库内交付 | 可执行验收 | 仍需外部证据 |
|---|---|---|---|
| 4–9 个月 | 三端 Host、平台验签、Native Renderer、LKG、四 Profile；Android Gradle SDK/Demo；iOS SDK/XCFramework 基线 | `make platform-check delivery-matrix android-demo-check ios-sdk-check`；HONOR API 35 | iOS 示例/真机/签名、HarmonyOS DevEco 工程与真机、Android 扩展设备矩阵、推送账号 |
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
| `android-demo-artifacts` | `make android-demo-check` | Android APK/AAB/AAR/Maven 与包安全属性 |
| `ios-sdk-artifacts` | `make ios-sdk-check` | iOS XCFramework、Swift consumer 与产物安全属性 |
| `historical-bytecode` | `make compatibility` | 15 项历史模块升级 |
| `sanitizers` | `make sanitizer-check` | Linux ASan+UBSan / macOS UBSan |
| `package-fuzz-smoke` | `make fuzz-check` | 包解析覆盖引导 smoke |

Android 与 iOS 另有 SDK 专项门禁：

| 命令 | 证明范围 |
|---|---|
| `make android-packages` | 构建 lint、Debug APK/AAB、R8 smoke APK、Release AAR 与本地 Maven |
| `make android-demo-check` | 在上述构建后检查 APK/AAB 签名、SDK、ABI、16 KiB、离线资源、Maven/AAR 一致性、POM 和模块篡改拒绝 |
| `make ios-sdk-check` | 生成并检查静态 XCFramework slice/架构/iOS 15、公开符号、Swift 6 consumer 与敏感内容 |

两个门禁都已登记在 `spec/release_gates.json`；前者要求 Android SDK，后者要求完整
Xcode，所以不并入可跨平台运行的 `release-check` 聚合命令。对应平台的 CI/发布任务
必须单独执行。

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
| `device-lab` | 已有 HONOR BRP-AN00/API 35 交互与状态恢复 smoke；仍需三端、多设备及相机/媒体/推送/后台结果 | QA/平台 |
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

## 当前状态与剩余三个核心阶段

共享边界加固已经完成：C ABI v3、Runtime 生命周期状态机、三端 LKG state 强绑定与
严格历史校验、cancel/close 后迟到回调丢弃，以及 `appear` absent→present 语义均已
落地。iOS SDK 基线也已完成：Swift Package、`PVMHost`、Privacy Manifest、完整
Runtime 静态 XCFramework 和 `make ios-sdk-check` 已提供；示例 App、真机、签名和审核
属于生产验收，不应写成已完成。

剩余核心阶段为：

1. **HarmonyOS 产品 SDK**：DevEco 工程、HAR/HSP、HUKS/文件/网络实现、ArkUI Renderer、
   基础 Capability、示例 HAP 与真机。当前仅有可移植合同。
2. **KMP/CMP 产品化（Kuikly 按需）**：KMP source set、Android/iOS actual Runtime、
   Compose Host 和 Maven 分发；只有产品采用 Kuikly 时才锁定版本并实现 Adapter。
3. **生产验收与运营**：iOS 示例/真机/archive/codesign，正式 signer/HSM、公钥轮换、
   三端正式签名包、全量设备矩阵、业务 Capability、性能 SLO、审计告警、红队、商店
   与支付沙箱。

发布操作见[发布与运维](OPERATIONS.md)，威胁与控制见[安全模型](SECURITY_MODEL.md)。
