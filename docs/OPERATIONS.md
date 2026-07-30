# 发布与运维

本文描述从 DSL 到设备 LKG 的标准操作路径。命令均从仓库根目录执行。

## 环境分层

| 环境 | 签名方式 | 模块服务 | 用途 |
|---|---|---|---|
| Local | `server/var/keys/` 开发密钥 | 本机 HTTP localhost | 演示、单元和端到端测试 |
| CI/Staging | 隔离测试 signer | HTTPS 测试仓库 | 集成、灰度演练、兼容验证 |
| Production | KMS/HSM signer | HTTPS、鉴权、CDN/私有仓库 | 正式发布 |

生产构建不得读取本地开发私钥。

## 本地闭环

```bash
make demo
```

如果只想分步运行：

```bash
make bootstrap build
make publish
PVM_ACTIVATION_TOKEN='replace-me' make serve
```

默认模块服务监听 `127.0.0.1:8080`。`Online Provisioned` 和 `Enterprise Managed` Manifest/模块需要 Bearer token。

## 发布前门禁

```bash
make release-check
```

门禁来源以 [`spec/release_gates.json`](../spec/release_gates.json) 为准：

| Gate | 验证内容 |
|---|---|
| `make test` | 编译、签名、篡改、路径、状态迁移、HTTP、灰度与 LKG |
| `make platform-check` | Android 完整 NDK、iOS 编译检查、Harmony DevEco 工程静态探测与 Node-API portable smoke |
| `make verify-contracts` | Host IDL 生成结果、DSL lint、Renderer conformance |
| `make docs-check` | README/docs 本地链接与 SVG XML |
| `make delivery-matrix` | Android/iOS/HarmonyOS × 四 Profile |
| `make android-demo-check` | Android Demo APK/AAB、Runtime AAR/Maven、R8 smoke 与安装包安全属性 |
| `make ios-sdk-check` | iOS 15 静态 XCFramework、Swift 6 consumer 与产物安全属性 |
| `make ios-demo-check` | iOS Simulator App、签名离线模块、Privacy Manifest 与 Package 接入 |
| `make harmony-sdk-check` | DevEco API 24 Runtime HAR、兼容 API 23 的 unsigned HAP、双 ABI 与离线资源 |
| `make compatibility` | 五业务域 × PVBC v1/v2/v3 |
| `make sanitizer-check` | Linux ASan+UBSan；macOS 26 使用 UBSan |
| `make fuzz-check` | Clang libFuzzer 包解析 smoke |

这些门禁不能替代 `externalRequired` 中的 HSM、商店、真机、支付沙箱和红队证据。

`android-demo-check`、`ios-sdk-check`、`ios-demo-check` 和
`harmony-sdk-check` 是需要各自平台 SDK 的独立自动门禁，不并入可跨平台运行的
`release-check` 聚合命令。

Android 门禁使用 API 36、NDK `28.0.13004108` 构建并验证：

- 可安装的 Debug APK 与 Debug AAB。
- 可复用的 Release AAR 及本地 Maven 仓库。
- 开启 R8 压缩和混淆的非 debuggable smoke APK。
- APK 签名、AAB JAR 签名、ZIP 16 KiB page alignment、内置模块/公钥/ABI 与篡改拒绝。
- 本地 Maven 与独立 AAR 字节一致，POM 保留 Runtime 的外部依赖。
- Release AAR 中两种 ABI 的 ELF `PT_LOAD` 段至少按 16 KiB 对齐。

执行命令：

```bash
make android-demo-check
```

产物写入 `dist/android/`。Debug APK/AAB 和 R8 smoke APK 使用 Debug/测试签名，
只用于开发、CI 与集成验收，不能作为生产签名或商店发布证据。Release AAR/Maven
是 Runtime 库产物，不包含最终 App 的正式签名；接入方仍必须在自己的 Android
工程中使用正式 application ID、release variant、keystore 或 Play App Signing
生成生产 APK/AAB。

交付矩阵产物仍是宿主工程输入。Android bootstrap 声明
`packageFormats: ["apk", "aab"]`；仓库生成的 Demo 包只证明示例集成链路，正式业务
App 必须使用自身签名策略构建。

在安装完整 Xcode 的 macOS 上，iOS SDK 发布任务还必须执行：

```bash
make ios-sdk-check
```

该门禁生成 `dist/ios/PVMBridge.xcframework`，检查 arm64 iPhoneOS 与
arm64/x86_64 Simulator slice、iOS 15 deployment target、C ABI v3/Objective-C 符号、
公开头文件、Swift 6 strict-concurrency、实际链接 consumer，以及私钥/本机路径泄漏。
它不会生成 `.xcarchive` 或 IPA，也不能代替 codesign、真机、entitlement、隐私问卷和
App Store 审核。

Simulator 示例接入还必须执行：

```bash
make ios-demo-check
make ios-demo-run
```

前者构建并校验 `PVMRuntimeDemo.app`；后者要求唯一已启动的 Simulator，安装并运行
该 App。需要复现 README 截图时使用 `make ios-demo-screenshot`，它只重置
`com.example.protected` Demo 的 Simulator 沙盒。该证据不能替代物理 iPhone、
`.xcarchive`、Apple Distribution codesign 或 IPA。

iOS 默认发布建议为 `offline_sealed`。任何在线字节码交付都必须针对实际模块能够改变
的功能评估
[Apple App Review Guidelines 2.5.2](https://developer.apple.com/app-store/review/guidelines/)；
自动门禁通过不等于商店天然合规。

在安装 DevEco Studio 6.1.1/API 24 的 macOS 上，HarmonyOS SDK 发布任务还必须执行：

```bash
make harmony-sdk-check
```

该门禁调用 `make harmony-packages`，构建兼容 API 23 的 Runtime HAR 和 Offline
Sealed Demo unsigned HAP，并检查 arm64-v8a/x86_64 C++17 Node-API Runtime、ArkUI、
模块、公钥与 bootstrap 一致性。产物写入 `dist/harmony/`。

当仓库路径包含 DevEco 不接受的空格或 `+` 时，先准备一次性纯 ASCII 工程：

```bash
python3 scripts/build_harmony_artifacts.py \
  --prepare-project /tmp/PVMRuntimeHarmonySigning
```

该命令只接受空目录，并注入当前 HarmonyOS Offline Sealed 交付输入。在临时工程的
`Project Structure > Signing Configs` 中为 `default` product 配置 Huawei 自动调试
签名后再构建 signed HAP；不得把 `signingConfigs`、证书、Profile 或密码复制回仓库。

unsigned HAP 只用于 Emulator/开发联调，不是华为商业真机或应用市场签名结果。
Emulator 使用：

```bash
make harmony-demo-run
make harmony-demo-screenshot
```

物理设备必须显式提供 USB 目标和 Huawei 签名 HAP：

```bash
HARMONY_DEVICE_TARGET=3RM0224B30000105 \
HARMONY_SIGNED_HAP=/path/to/huawei-debug-signed.hap \
make harmony-device-screenshot
```

该路径已在 HUAWEI Pura 70 ADY-AL10（HarmonyOS 6.1、API 23 兼容）使用 Huawei debug
signed HAP 通过：真实 Offline Sealed 模块完成 count `0 → 1 → 2`、异步存储
`Status: Not set`、输入 `Alice`，Home、force-stop、重启后状态恢复，并写出
`docs/assets/harmony-demo.png`。这不是 commercial/release/AppGallery 签名或完整
设备矩阵。HUKS、线上 Module Store、完整 Capability 和更多物理设备仍需独立验收。

HarmonyOS 构建使用 CMake、ohpm 与 Hvigor，不依赖 Gradle。不要为了 HarmonyOS
验收删除 `~/.gradle`；如需同时执行 Android 门禁，应使用任务专属
`GRADLE_USER_HOME` 隔离缓存，而不是清理其他桌面项目共享的 Gradle 缓存。

## 编译与发布

### 本地私钥

```bash
PYTHONPATH=server/src python3 -m pvm_server.publish \
  server/sample/counter.pvm.json \
  --private-key server/var/keys/dev-private.pem \
  --repository server/var/repository
```

### 远程 signer

```bash
PYTHONPATH=server/src python3 -m pvm_server.publish \
  path/to/module.pvm.json \
  --signer-command '/opt/company/pvm-signer --environment production' \
  --repository path/to/repository
```

signer 从 stdin 接收原始 payload，并只向 stdout 返回 64 字节 Ed25519 签名。错误信息写 stderr，退出码必须非零。

发布器会：

1. 解析 DSL 并执行 lint/Host IDL 检查。
2. 编译、签名并写入内容寻址模块。
3. 写入按模块 Hash 的访问策略。
4. 保留上一版签名信封到 `history/`。
5. 创建新的签名 Manifest payload。
6. 原子替换控制文件并把 rollout 重置为 100%。

同一 release 与同一 Hash 重复发布是幂等操作；同一 release 不同内容或更小 release 会被拒绝。

## 仓库布局

```text
repository/
├── access/<sha256>.json
├── modules/<sha256>.pvm
└── apps/<application>/<channel>/<platform>/<profile>/
    ├── manifest.json
    └── history/<release>-<sha256>.json
```

`manifest.json` 是服务端控制对象：

```json
{
  "control_format": 1,
  "current": {"envelope_format": 1, "...": "..."},
  "previous": {"envelope_format": 1, "...": "..."},
  "rollout_percentage": 100
}
```

服务端只下发选中的 `current` 或 `previous` 签名信封，不下发控制字段。

## 灰度

把新版本限制到 10% 的稳定设备桶：

```bash
PYTHONPATH=server/src python3 -m pvm_server.release \
  path/to/manifest.json --percentage 10
```

设备通过 `X-PVM-Installation-ID` 进入稳定 Hash 桶。没有安装 ID 的请求在部分灰度期间选择 previous，避免随机漂移。

逐步扩大：

```bash
PYTHONPATH=server/src python3 -m pvm_server.release \
  path/to/manifest.json --percentage 25

PYTHONPATH=server/src python3 -m pvm_server.release \
  path/to/manifest.json --percentage 100
```

## 止血与业务回退

停止更多设备升级：

```bash
PYTHONPATH=server/src python3 -m pvm_server.release \
  path/to/manifest.json --rollback
```

该操作把 rollout 设为 0%，不会降低已经安装新版本设备的 release floor。若已升级设备也必须回到旧逻辑：

1. 从旧 DSL/提交恢复业务行为。
2. 将 `module.release` 提升到比问题版本更大的值。
3. 重新编译、签名和发布。

不要删除客户端状态或放宽防回滚来实现运营回退。

## Manifest 与模块服务

启动：

```bash
PVM_ACTIVATION_TOKEN='replace-me' \
PYTHONPATH=server/src \
python3 -m pvm_server.serve \
  --repository server/var/repository \
  --audit-log server/var/audit.jsonl
```

重要行为：

- Manifest 使用 `private, max-age=60` 和 ETag。
- 模块使用 Hash URL 与一年 immutable 缓存。
- 受保护模块使用 private cache；公共 Profile 可使用 public cache。
- 缺失或损坏 access policy 默认要求激活。
- 路径段、平台、Profile 和模块 Hash 都进行严格检查。

## 审计

参考服务写 JSONL：

```json
{"event":"manifest","path":"apps/.../manifest.json","release":4,"rollout":10,"bucket":7,"timestamp":0}
{"event":"module","sha256":"...","size":638,"timestamp":0}
{"event":"authorization_denied","sha256":"...","timestamp":0}
```

生产接入至少应按以下维度聚合：

- Manifest 200/304/401/409/500。
- release、平台、Profile、灰度桶和客户端版本。
- 模块下载量、Hash、大小、CDN 命中和延迟。
- Manifest/模块验签失败、绑定失败和防回滚拒绝。
- LKG 命中率、更新失败率和首次激活成功率。

日志不得记录 activation token、私钥、完整状态或用户敏感数据。

## 故障处理

### Manifest 服务不可用

- 已安装用户继续使用符合 floor 的 LKG。
- 首次安装用户显示内置 fallback UI，并重试带退避的激活。
- 不要返回未签名的临时 Manifest。

### 新模块验证失败

- 立即把 rollout 降为 0。
- 保留问题 `.pvm`、Manifest 信封、编译器版本和 signer 审计用于复盘。
- 用更高 release 发布修复，不能覆盖内容寻址文件。

### 签名密钥疑似泄露

- 停止 signer 权限和所有新发布。
- 冻结 Manifest 控制写入，保留模块读取以维持 LKG。
- 根据预先演练的 App 公钥轮换计划发布新信任根。
- 不能仅删除仓库旧模块：离线设备仍可能接受被泄露 key 签名且高 release 的恶意内容。

### 状态迁移失败

- 检查新状态字段是否保留旧 `persistence_id`。
- 类型变化需要显式业务迁移版本，不能让 VM 重新解释原字节。
- 修复后使用更高 release 重发；不要清空用户数据作为默认策略。

## 发布记录建议

每次正式发布应归档：

- DSL 源提交与编译器提交。
- Host IDL/生成产物版本。
- application/channel/platform/profile/release。
- 模块 SHA-256、Manifest payload Hash 和 signer key ID。
- release-check、对应平台 `android-demo-check`/`ios-sdk-check` 结果与外部证据链接。
- 灰度时间线、指标、止血条件和负责人。
