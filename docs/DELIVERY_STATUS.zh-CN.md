[English](DELIVERY_STATUS.md)

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
| 新移动端 C ABI | v4 强绑定 + UI Wire v2 补丁；v1–v3 完整树兼容 |
| 平台 | Android、iOS、HarmonyOS；desktop 参考 Host |
| Delivery Profile | 4 |
| 自动交付矩阵 | 3 平台 × 4 Profile = 12 套宿主嵌入输入 |
| Android Gradle 交付 | Debug APK/AAB、R8 smoke APK、Release AAR、本地 Maven |
| Android SDK 坐标 | `com.protectedvm:pvm-runtime:0.5.0` |
| Android 工具链 | compile/target API 36、NDK 28、双 ABI、16 KiB 对齐 |
| Android 真机 | HONOR BRP-AN00、API 35 交互与状态恢复通过 |
| iOS SDK 交付 | Swift Package、`@MainActor PVMHost`、Privacy Manifest、完整二进制 XCFramework 门禁 |
| iOS XCFramework | `make ios-sdk-check` 生成 `dist/ios/PVMRuntime.xcframework` |
| iOS Demo | Xcode App target；iPhone 17 Pro Max Simulator（iOS 26.2）交互与截图通过 |
| HarmonyOS SDK 交付 | DevEco API 24 工程（兼容 API 23）、Runtime HAR、unsigned Emulator HAP |
| HarmonyOS Native ABI | arm64-v8a、x86_64 C++17 Node-API Runtime |
| HarmonyOS 运行证据 | HUAWEI Pura 70、HarmonyOS 6.1（API 23 兼容）；Huawei debug signed HAP 交互、恢复与截图通过 |
| KMP SDK | commonMain/JVM/iOS Kotlin/Native；`com.protectedvm:pvm-runtime-kmp:0.5.0` |
| SDK Release 集合 | AAR/Maven、Binary Swift Package/XCFramework、HAR、SHA-256 清单 |
| 自动化 | GitHub Actions 核心、Android、Apple、KMP、容器与显式生产签名发布工作流 |
| 生产包 | 正式签名 APK/AAB、IPA、HAP 仍由目标工程与发布账号生成 |
| 历史兼容矩阵 | 5 业务域 × PVBC v1/v2/v3 = 15 |

## 仓库能力状态

| 领域 | 仓库已实现 | 自动化证据 | 外部缺口 |
|---|---|---|---|
| DSL/编译器 | 状态、页面、处理器、Effect、输入事件值、Profile/IDL/预算检查 | `make test verify-contracts` | 完整语言愿景、IDE、真实业务规模 |
| 模块安全 | 确定性 PVBC、Ed25519、C ABI v4 五项绑定、防回滚、验证器 | `make test fuzz-check sanitizer-check` | 长时 fuzz、独立安全审计 |
| 状态演进 | v4 稳定 ID、改名/新增迁移、类型冲突拒绝 | 状态迁移端到端测试 | 大版本业务迁移工具链 |
| 发布服务 | 内容寻址、访问策略、签名 Manifest、ETag、灰度、审计、TLS、健康检查、请求 ID、容器 | HTTP/篡改/灰度/LKG/服务边界测试 | 生产 CDN、数据库、身份系统与多副本 HA |
| Android | Gradle Library/Demo、Kotlin/JNI/View、严格绑定的 Module Store、双 ABI `.so`、AAR/Maven、Debug APK/AAB、R8 smoke | `make platform-check android-demo-check`；HONOR API 35 人工真机验收 | Compose/CMP、更多设备/性能、业务 Capability、正式签名与商店 |
| iOS | Swift Package、Objective-C++/Swift、`PVMHost`、UIKit/SwiftUI、严格绑定的 CryptoKit Store、Privacy Manifest、完整二进制 XCFramework、Xcode Demo | `make platform-check ios-sdk-check ios-demo-check`；iOS 26.2 Simulator 交互/截图 | 真机、archive/Apple Distribution codesign、完整 NativeSurface、审核 |
| HarmonyOS | DevEco API 24/兼容 API 23 工程、C++17 Node-API/ArkTS Host、ArkUI Renderer、Runtime HAR、Offline Sealed unsigned Demo HAP | `make harmony-sdk-check`；HAR/HAP 与双 ABI 已真实构建；Pura 70 debug signed HAP 真机 smoke | commercial/release/AppGallery 签名、HUKS、线上 Module Store、完整 Capability 与更多物理设备实验室 |
| KMP | commonMain Runtime Port、生命周期/事件模型、JVM 与三种 iOS target、Maven publication | `make kmp-check kmp-packages` | 目标 Compose 版本、平台 actual Host 与 UI 真机验证 |
| Capability | 27 项版本化合同；Android 5 项、iOS 4 项、HarmonyOS 2 项基础 Adapter | `make verify-contracts platform-check` | HarmonyOS 其余 25 项及其他供应商/系统能力 |
| Delivery | 四 Profile 与 12 套宿主嵌入输入；Android 有 Demo APK/AAB 和 SDK AAR/Maven；iOS 有 XCFramework 与 Simulator Demo；HarmonyOS 有 HAR 与 unsigned Emulator HAP | `make delivery-matrix android-demo-check ios-sdk-check ios-demo-check harmony-sdk-check` | 正式签名三端安装包、各商店/MDM 上传和审批 |
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
| 统一 Host | `@MainActor PVMHost` | C ABI v4 / UI Wire v2、Renderer/Capability、状态与关闭入口 |
| Privacy Manifest | `PrivacyInfo.xcprivacy` | Swift Runtime target 资源基线；目标 App 仍需按实际数据用途合并审核声明 |
| XCFramework | `dist/ios/PVMRuntime.xcframework` | `make ios-sdk-check` 可重复生成，不等同 IPA |
| slice | arm64 iPhoneOS；arm64/x86_64 Simulator | iOS 15 完整预编译 Swift/Objective-C++/C++ Runtime |
| consumer | 稳定 Swift Interface + Swift 6 complete strict-concurrency + 二进制链接 probe | warnings-as-errors，并验证目标只链接预编译 Framework |
| 产物安全 | 自动扫描公开头、私钥/模块后缀和本机绝对路径 | 不替代独立安全审计 |
| Xcode Demo | `client/platform/ios/demo/PVMRuntimeDemo.xcodeproj` | 本地 Package、真实签名模块、基础 Capability 与状态恢复 |
| Simulator | iPhone 17 Pro Max、iOS 26.2 | `count=2 / Status=Not set / Alice` 交互及原始截图 |
| Demo 门禁 | `make ios-demo-check` | arm64 App、ad-hoc codesign、iOS 15、资源/绑定/Privacy Manifest |

当前 iOS Demo 只生成 Simulator `.app` 并进行本地 ad-hoc codesign，不生成
`.xcarchive` 或 IPA，也不代表真机生命周期、Apple Distribution 签名、entitlement、
隐私问卷或 App Store 审核。默认建议 `offline_sealed`；在线字节码交付必须按实际产品评估
[Apple App Review Guidelines 2.5.2](https://developer.apple.com/app-store/review/guidelines/)，
不能因为模块有签名或 VM 受限就宣称天然合规。

## HarmonyOS SDK 本轮交付证据

| 证据 | 结果 | 说明 |
|---|---|---|
| DevEco 工程 | API 24，`compatibleSdkVersion` API 23 | Runtime HAR 与 Demo HAP 两个模块 |
| Runtime HAR | `dist/harmony/pvm-runtime-0.5.0.har` | ArkTS Host、ArkUI Renderer 与 C++17 VM |
| Demo HAP | `dist/harmony/PVMRuntime-demo-unsigned.hap` | Offline Sealed unsigned 开发产物，仅面向 Emulator |
| Native ABI | arm64-v8a、x86_64 | 两个 ABI 都包含完整 Node-API/C++17 Runtime |
| 离线资源 | module、公钥、bootstrap | 平台/Profile/Hash 绑定进入 HAP |
| 构建门禁 | `make harmony-sdk-check` | 构建并检查 HAR/HAP、ABI 和离线资源 |
| 真机 | HUAWEI Pura 70 ADY-AL10、HarmonyOS 6.1（API 23 兼容） | USB `3RM0224B30000105` |
| 真机 HAP | Huawei debug signed HAP | 签名验证后安装并运行真实 Offline Sealed 模块 |
| 自动交互 | 通过 | count 0→1→2、`Status: Not set`、`Alice`、Home/force-stop/relaunch 恢复 |
| 截图 | `docs/assets/harmony-demo.png` | 由目标设备直接采集的原始 PNG |

`dist/harmony/PVMRuntime-demo-unsigned.hap` 仍不具备华为商业真机或应用市场要求的
签名身份；本次真机使用的是另行生成并验证的 Huawei debug signed HAP。该结果不是
commercial/release/AppGallery 签名，并且只覆盖一台 Pura 70。HUKS、线上 Module
Store、完整 Capability 和更多物理设备结果仍不在本轮证据内。

## 原计划时间段映射

仓库把原 0–36 个月方案压缩为一条可执行工程基线：

| 时间段 | 仓库内交付 | 可执行验收 | 仍需外部证据 |
|---|---|---|---|
| 4–9 个月 | 三端 Host、平台验签、Native Renderer、LKG、四 Profile；Android Gradle SDK/Demo；iOS SDK/XCFramework/Xcode Demo；HarmonyOS HAR/unsigned Emulator HAP | `make platform-check delivery-matrix android-demo-check ios-sdk-check ios-demo-check harmony-sdk-check`；HONOR API 35；iOS 26.2 Simulator；Pura 70 HarmonyOS 6.1（API 23 兼容） | iOS 真机/发布签名、HarmonyOS commercial/release/AppGallery 签名与更多真机、Android 扩展设备矩阵、推送账号 |
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
| `documentation` | `make docs-check` | 中英文 Markdown 配对、本地链接和视觉资源完整性 |
| `delivery-profiles` | `make delivery-matrix` | 12 套 Profile 产物 |
| `android-demo-artifacts` | `make android-demo-check` | Android APK/AAB/AAR/Maven 与包安全属性 |
| `ios-sdk-artifacts` | `make ios-sdk-check` | iOS XCFramework、Swift consumer 与产物安全属性 |
| `ios-demo-artifact` | `make ios-demo-check` | iOS Simulator App、签名离线模块与 Package 集成 |
| `harmony-sdk-artifacts` | `make harmony-sdk-check` | HarmonyOS HAR、unsigned Emulator HAP、双 ABI 与离线资源 |
| `kmp-sdk-artifacts` | `make kmp-check` | commonMain、JVM 和 iOS Simulator ARM64 编译与生命周期测试 |
| `sdk-release-assets` | `make sdk-release-assets` | 带版本的 AAR/Maven、Binary Swift Package/XCFramework、HAR 与校验清单 |
| `historical-bytecode` | `make compatibility` | 15 项历史模块升级 |
| `sanitizers` | `make sanitizer-check` | Linux ASan+UBSan / macOS UBSan |
| `package-fuzz-smoke` | `make fuzz-check` | 包解析覆盖引导 smoke |

三个移动平台另有 SDK 专项门禁：

| 命令 | 证明范围 |
|---|---|
| `make android-packages` | 构建 lint、Debug APK/AAB、R8 smoke APK、Release AAR 与本地 Maven |
| `make android-demo-check` | 在上述构建后检查 APK/AAB 签名、SDK、ABI、16 KiB、离线资源、Maven/AAR 一致性、POM 和模块篡改拒绝 |
| `make ios-sdk-check` | 生成并检查完整二进制 XCFramework slice/架构/iOS 15、公开符号、Swift 6 consumer 与敏感内容 |
| `make ios-demo-check` | 构建并检查 Xcode Simulator Demo、ad-hoc 签名、Privacy Manifest 与 Offline Sealed 资源 |
| `make ios-demo-run` | 安装并启动到唯一已 Boot 的 iOS Simulator |
| `make harmony-packages` | 使用 DevEco API 24 构建 Runtime HAR 与兼容 API 23 的 unsigned Demo HAP |
| `make harmony-sdk-check` | 构建并检查 HAR/HAP、arm64-v8a/x86_64 Runtime 和 Offline Sealed 资源 |
| `make harmony-demo-run` | 安装并启动到唯一 HarmonyOS Emulator |
| `make harmony-demo-screenshot` | 在 Emulator 执行交互并采集原始截图 |
| `make harmony-device-run` | 使用显式 USB 目标和 Huawei 签名 HAP 安装、启动与验证 |
| `make harmony-device-screenshot` | 在物理设备执行确定性交互、状态恢复并采集原始截图；Pura 70 已通过 |
| `make kmp-packages` | 构建并发布 JVM、metadata 和 Kotlin/Native Maven 变体到 `dist/kmp/maven` |

Android、iOS 和 HarmonyOS 产物门禁都已登记在 `spec/release_gates.json`；它们分别
要求 Android SDK、完整 Xcode 和 DevEco SDK，所以不并入可跨平台运行的
`release-check` 聚合命令。对应平台的 CI/发布任务必须单独执行。运行/截图命令不是
产物门禁；本轮物理设备结果是使用显式 USB 目标和 Huawei debug signed HAP 得到的
独立 smoke 证据。

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
| `device-lab` | 已有 HONOR BRP-AN00/API 35 与 HUAWEI Pura 70/HarmonyOS 6.1（API 23 兼容）交互、状态恢复 smoke；仍需三端多物理设备及相机/媒体/推送/后台结果 | QA/平台 |
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

共享边界加固已经完成：C ABI v4 / UI Wire v2、Runtime 生命周期状态机、三端 LKG state 强绑定与
严格历史校验、cancel/close 后迟到回调丢弃，以及 `appear` absent→present 语义均已
落地。iOS SDK 基线也已完成：Swift Package、`PVMHost`、Privacy Manifest、完整
Runtime 完整二进制 XCFramework 和 `make ios-sdk-check` 已提供；Xcode Demo 与 Simulator
交互/截图也已完成。真机、Archive、Apple Distribution 签名和审核仍属于生产验收，
不应写成已完成。

剩余核心阶段为：

1. **HarmonyOS 产品化补齐**：DevEco API 24 工程、Runtime HAR、ArkUI Renderer、
   两项基础 Capability 与 unsigned Emulator HAP 已完成构建，Huawei debug signed
   HAP 已在一台 Pura 70 完成交互、状态恢复和截图；仍需 HUKS、线上 Module Store、
   完整 Capability、commercial/release/AppGallery 签名 HAP 与更多物理真机。
2. **KMP/CMP 产品化（Kuikly 按需）**：commonMain、JVM/iOS 编译、测试和 Maven
   分发已完成；仍需 Android/iOS actual Runtime 与选定版本的 Compose Host。只有产品
   采用 Kuikly 时才锁定版本并实现 Adapter。
3. **生产验收与运营**：iOS 真机/archive/Apple Distribution codesign，正式 signer/HSM、公钥轮换、
   三端正式签名包、全量设备矩阵、业务 Capability、性能 SLO、审计告警、红队、商店
   与支付沙箱。

发布操作见[发布与运维](OPERATIONS.zh-CN.md)，威胁与控制见[安全模型](SECURITY_MODEL.zh-CN.md)。
