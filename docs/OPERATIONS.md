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
| `make platform-check` | Android 完整 NDK、iOS 编译检查、Harmony Node-API 可移植检查 |
| `make verify-contracts` | Host IDL 生成结果、DSL lint、Renderer conformance |
| `make docs-check` | README/docs 本地链接与 SVG XML |
| `make delivery-matrix` | Android/iOS/HarmonyOS × 四 Profile |
| `make compatibility` | 五业务域 × PVBC v1/v2/v3 |
| `make sanitizer-check` | Linux ASan+UBSan；macOS 26 使用 UBSan |
| `make fuzz-check` | Clang libFuzzer 包解析 smoke |

这些门禁不能替代 `externalRequired` 中的 HSM、商店、真机、支付沙箱和红队证据。

交付矩阵产物是宿主工程输入，不是最终安装包。Android bootstrap 声明 `packageFormats: ["apk", "aab"]`，最终 APK/AAB 必须在目标 Android Gradle 工程中使用正式 application ID、variant、keystore 和签名策略构建。

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
- release-check 结果与外部证据链接。
- 灰度时间线、指标、止血条件和负责人。
