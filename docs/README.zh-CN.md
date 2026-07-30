[English](README.md)

# PVM Runtime 文档中心

这里记录 PVM Runtime 的设计约束、可执行合同和生产接入边界。README 用于快速理解项目；本目录用于回答“为什么这样设计”“怎样正确集成”和“哪些证据才算完成”。

## 推荐阅读顺序

### 第一次了解项目

1. [项目首页](../README.zh-CN.md)
2. [架构与数据流](ARCHITECTURE.zh-CN.md)
3. [安全模型](SECURITY_MODEL.zh-CN.md)
4. [功能完成度](FUNCTIONAL_STATUS.zh-CN.md)
5. [交付状态](DELIVERY_STATUS.zh-CN.md)

### 编写业务模块

1. [DSL 与字节码](DSL_V1.zh-CN.md)
2. [选择性迁移](MIGRATION.zh-CN.md)
3. [示例模块](../server/sample/counter.pvm.json)
4. [Host IDL](../spec/host_idl.json)
5. `make verify-contracts`

### 接入移动端 App

1. [三端集成](PLATFORM_INTEGRATION.zh-CN.md)
2. [C ABI](../client/include/pvm/runtime_c.h)
3. 对应平台的 `client/platform/<platform>/`
4. `make platform-check delivery-matrix`
5. Android 额外运行 `make android-demo-check`
6. iOS 额外运行 `make ios-sdk-check ios-demo-check`
7. HarmonyOS 额外运行 `make harmony-sdk-check`
8. KMP 接入额外运行 `make kmp-check`

### 负责发布与值班

1. [发布与运维](OPERATIONS.zh-CN.md)
2. [安全模型](SECURITY_MODEL.zh-CN.md)
3. [发布门禁合同](../spec/release_gates.json)
4. `make release-check`

## 文档地图

| 文档 | 面向角色 | 主要问题 |
|---|---|---|
| [ARCHITECTURE.zh-CN.md](ARCHITECTURE.zh-CN.md) | 架构师、Runtime/平台开发 | 组件如何协作，数据和信任怎样流动 |
| [SECURITY_MODEL.zh-CN.md](SECURITY_MODEL.zh-CN.md) | 安全、发布、平台开发 | 防什么、不防什么、密钥和失败策略是什么 |
| [DSL_V1.zh-CN.md](DSL_V1.zh-CN.md) | DSL/业务开发 | 能表达什么、如何编译、怎样兼容升级 |
| [MIGRATION.zh-CN.md](MIGRATION.zh-CN.md) | 老项目负责人、业务开发 | 怎样按类或模块选择性迁移并复核结果 |
| [PLATFORM_INTEGRATION.zh-CN.md](PLATFORM_INTEGRATION.zh-CN.md) | Android/iOS/HarmonyOS 开发 | 怎样连接 VM、渲染器、验签和模块缓存 |
| [OPERATIONS.zh-CN.md](OPERATIONS.zh-CN.md) | CI/CD、SRE、发布负责人 | 怎样签名、发布、灰度、止血和审计 |
| [DELIVERY_STATUS.zh-CN.md](DELIVERY_STATUS.zh-CN.md) | 项目负责人、验收人员 | 哪些由仓库证明，哪些必须取得外部证据 |
| [FUNCTIONAL_STATUS.zh-CN.md](FUNCTIONAL_STATUS.zh-CN.md) | 产品、平台、验收人员 | 哪些功能可运行，哪些只是合同或接入点 |

## 核心术语

| 术语 | 含义 |
|---|---|
| DSL | 构建时业务输入，描述状态、页面、处理器和 Effect，不进入生产模块 |
| PVBC | PVM 私有字节码 payload；当前默认版本为 v5 |
| PVMP | 包含 PVBC 和 Ed25519 签名的模块容器 |
| Manifest | 经过 Ed25519 签名的模块发布描述，绑定 application、channel、platform、profile、release 和 Hash |
| UIHost | 把 VM 的中立 UI Tree 映射到原生 UI 框架的宿主接口 |
| Capability Host | 承载支付、网络、存储、相机等原生能力的版本化宿主接口 |
| LKG | Last Known Good，最后一次完整验证并原子切换成功的本地模块 |
| Release floor | 客户端允许接受的最低单调发布序号，用于首装和升级防回滚 |
| Delivery Profile | 决定签名模块如何进入设备的交付策略，不改变 DSL/VM 语义 |

## 版本关系

| 组件 | 当前版本/范围 | 兼容策略 |
|---|---|---|
| Runtime | 5 | 读取 PVBC v1–v5 |
| 默认字节码 | PVBC v5 | v4 稳定状态 ID；v5 输入事件值 |
| 模块包 | PVMP v1 | Ed25519，64 字节签名 |
| Manifest 信封 | v1 | Ed25519 签名 canonical JSON payload |
| Host IDL | schema v1 | 生成接口必须与 `generated/host/` 一致 |

## 当前可运行交付

| 入口 | 输出或证明 |
|---|---|
| `make demo` | 桌面端签名、发布、下载、执行与状态恢复闭环 |
| `make android-demo-check` | Debug APK/AAB、R8 smoke APK、Release AAR/Maven 与包安全检查 |
| `make ios-sdk-check` | iOS 15 完整二进制 XCFramework、Swift 6 consumer 与产物安全检查 |
| `make ios-demo-check` | Xcode Simulator App、签名离线模块、Privacy Manifest 与 Package 接入 |
| `make harmony-sdk-check` | DevEco API 24 Runtime HAR、unsigned Emulator HAP、双 ABI 与离线资源检查 |
| `make kmp-check` | commonMain/JVM/iOS Kotlin/Native 编译与生命周期测试 |
| `make sdk-release-assets` | 三端预编译 AAR/Maven、Binary Swift Package/XCFramework、HAR 与 SHA-256 清单 |
| `make release-check` | 核心、三端可编译部分、兼容、模糊测试、文档与交付矩阵 |

Android Demo 已在 HONOR BRP-AN00（API 35）验证；这是一台设备的 smoke 结果。iOS
已提供 Swift Package、`PVMHost`、Privacy Manifest、XCFramework 与 Xcode Demo，并
在 iOS 26.2 Simulator 完成交互/截图；真机和正式发布签名仍待完成。HarmonyOS 已有
DevEco API 24（兼容 API 23）工程，真实构建 Runtime HAR 和 unsigned Emulator HAP，
并包含 arm64-v8a/x86_64 C++17 Node-API、ArkTS Host 与 ArkUI Renderer。Huawei
debug signed HAP 已在 HUAWEI Pura 70 ADY-AL10（HarmonyOS 6.1、API 23 兼容）运行真实
Offline Sealed 模块，自动验证计数、异步存储、文本输入、Home/force-stop 后重启恢复
并生成原始截图。该结果不是 commercial/release/AppGallery 签名，也只覆盖这一台设备；
HUKS、线上 Module Store、完整 Capability 和更多物理设备仍待完成。KMP 公共模块
已经进入产品构建并可生成 Maven 制品；Compose/CMP 平台 Host 与 Kuikly 仍需根据
业务选型完成。剩余工作按
[功能完成度](FUNCTIONAL_STATUS.zh-CN.md)中的核心阶段推进。

## 文档维护规则

- 英文文件使用 `NAME.md`，简体中文使用 `NAME.zh-CN.md`；同一个 PR 必须同时更新两种语言。
- 描述“已实现”时必须能指向代码、生成产物或自动化门禁。
- 商店审核、HSM、商业 SDK、真机和红队等外部状态只能记录为证据，不得写成仓库自动完成。
- 改动字节码、Manifest、C ABI 或 Host IDL 时，同时更新对应文档和兼容测试。
- 示例命令必须从仓库根目录可运行；发布命令不得默认引用生产密钥。
- `make docs-check` 会强制检查双语配对、互链、本地链接和视觉资源完整性。
