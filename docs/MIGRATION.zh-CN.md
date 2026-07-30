[English](MIGRATION.md)

# 大型老项目的选择性迁移

PVM 迁移分为“本地只读扫描”和“生成后人工复核”两个步骤，不会重写源项目。一次
迁移可以选择单个类、多个类、一个模块目录、多个模块目录，也可以把类与模块选择器
组合使用。

## 支持的源码

当前无额外依赖的扫描器可以识别 Kotlin、Java、Swift 和 ArkTS，也就是 `.kt`、
`.java`、`.swift` 与 `.ets`，并记录：

- 类、结构体、接口等声明、import 和被引用的本地声明；
- 具有安全字面量初始值的可变 `int`、`bool`、`string` 状态；
- 可映射到 PVM 的 UI 节点提示；
- 可能需要的 Host Capability；
- 需要人工处理的反射、并发、动态加载、自定义绘制和 Web 内容。

扫描器会忽略构建产物、依赖目录、软链接、非 UTF-8 文件，以及单个超过 2 MiB 的
源码文件。

## 先扫描再转换

所有命令都从 PVM Runtime 仓库根目录执行。扫描整个源码目录只生成清单，不会执行
转换：

```bash
PYTHONPATH=server/src python3 -m pvm_server.migrate scan \
  /path/to/legacy-project \
  --output build/migration/inventory.json
```

单个类可以使用简单类名、完整限定名，或者无歧义的
`相对路径.ext:类名`：

```bash
PYTHONPATH=server/src python3 -m pvm_server.migrate scan \
  /path/to/legacy-project \
  --class com.example.checkout.CheckoutViewModel
```

重复 `--class` 就能同时选择多个类：

```bash
PYTHONPATH=server/src python3 -m pvm_server.migrate scan \
  /path/to/legacy-project \
  --class CheckoutViewModel \
  --class CheckoutRepository \
  --class app/profile/ProfileView.swift:ProfileView
```

也可以选择一个或多个模块目录。Android 常用的 `:feature:checkout` 会被识别为
`feature/checkout`：

```bash
PYTHONPATH=server/src python3 -m pvm_server.migrate scan \
  /path/to/legacy-project \
  --module :feature:checkout \
  --module ios/Features/Profile
```

类和模块选择范围会取并集。增加 `--include-dependencies` 后，工具会自动加入源目录
中能够唯一确定、且被已选代码引用的本地声明；不增加时，这些依赖会进入
`unselectedLocalDependencies`，等待明确确认。

## 生成迁移骨架

`convert` 至少需要一个 `--class` 或 `--module`，因此不会因为漏写参数而把整个大型
项目直接转换：

```bash
PYTHONPATH=server/src python3 -m pvm_server.migrate convert \
  /path/to/legacy-project \
  --class CheckoutViewModel \
  --class CheckoutRepository \
  --include-dependencies \
  --application-id com.company.existingapp \
  --platform android \
  --profile offline_sealed \
  --module-id checkout.flow \
  --release 1 \
  --output build/migration/checkout
```

Android、iOS、HarmonyOS 必须分别执行转换，因为 PVM 模块会绑定一个明确的
Application ID、平台、交付 Profile 和 Release。

输出目录包括：

```text
build/migration/checkout/
├── module.pvm.json          已通过真实编译器校验的 DSL 骨架
├── capabilities.json       Capability 决策及 Adapter/测试证据
├── migration-approvals.json 每一项扫描发现的复核决定
├── migration-cases.json     与老项目测试绑定的行为用例
├── migration-report.json   机器可读的选择范围和复核结果
└── migration-report.md     中英文人工复核清单
```

输出必须位于老项目源码根目录之外。已有输出默认不会被覆盖；只有显式增加
`--force` 才会替换工具自己生成的文件，目录中存在其他文件时仍会拒绝操作。

## 哪些内容会自动转换

工具会把具有安全字面量初始值的可变状态加入 DSL State Schema。非空字符串默认值会
被脱敏；名称中包含凭据、Token、密码、私钥等特征的字段不会复制。多个类中出现同名
状态时，会自动使用来源声明隔离名称。

生成页面会展示已经转换的状态，并在写入前交给真实 PVM 编译器验证。UI 提示不会被
冒充为已经完成的布局：原生 UI Builder、Modifier、Constraint 和自定义 View 仍需
人工复核，才能保持原来的行为。

Capability 只会写入建议清单，不会自动授予模块。应先审核 `capabilities.json`，
只批准最小集合，再用老项目现有的登录、网络、支付、存储等 Service 实现对应能力。

## 验证门禁

转换完成后可以立即运行结构验证：

```bash
PYTHONPATH=server/src python3 -m pvm_server.migrate verify \
  build/migration/checkout \
  --source /path/to/legacy-project
```

工具会按原来的选择范围重新扫描，并逐个比较已选源码文件的 SHA-256；同时要求 DSL
使用规范 JSON 格式，通过真实 PVM 编译器和版本化 Host IDL lint。结构验证成功会写入
`verification.json`，结果为 `"structurally_valid"`，但这还不是生产验收。

严格验证前，需要处理 `migration-approvals.json` 中的每一项。最终状态只能是
`resolved` 或 `accepted`，并且必须填写说明：

```json
{
  "id": "generated-stable-id",
  "status": "resolved",
  "note": "已经加入 CheckoutRepository，并复用了原有单元测试。"
}
```

`capabilities.json` 中的每项能力也必须作出决定：

- `approved` 必须填写 Adapter，并至少关联一个测试标识；
- `excluded` 必须填写排除原因；
- `pending` 会直接阻断严格验证。

`module.pvm.json` 声明的 Capability 必须与批准项完全一致，防止扫描提示被自动当成
权限，也防止人工编辑 DSL 时加入未经审核的 Host 调用。

在 `migration-cases.json` 中增加行为用例：

```json
{
  "schemaVersion": 1,
  "cases": [
    {
      "name": "结算页初始状态",
      "legacyEvidence": "CheckoutViewModelTest#initialState",
      "steps": [
        {
          "expectedOutput": [
            "text=\"CheckoutViewModel\"",
            "text=\"total: 0\""
          ],
          "forbiddenOutput": ["error:"]
        }
      ]
    }
  ]
}
```

`legacyEvidence` 必须指向老实现已有的测试或断言证据。每个 Case 使用独立状态文件；
后续步骤可以增加 `"tapIndex": 0`，同一个 Case 内会保留前一步状态。

构建桌面验证器并生成开发密钥后执行严格门禁：

```bash
make bootstrap build

PYTHONPATH=server/src python3 -m pvm_server.migrate verify \
  build/migration/checkout \
  --source /path/to/legacy-project \
  --strict \
  --runtime build/client/pvm_cli \
  --private-key server/var/keys/dev-private.pem \
  --public-key server/var/keys/dev-public.pem
```

严格验证会使用指定开发密钥签名模块，通过 C++17 VM 加载并执行全部行为步骤，再检查
必须出现和禁止出现的输出。源码漂移、DSL 错误、未完成复核、Capability 决策不一致、
缺少老代码证据、Runtime 失败或行为不一致都会返回非零退出码。只有
`verification.json` 中 `"result": "verified"` 才算通过。

行为验证器不会执行 JSON 中携带的任意老项目命令；老项目所引用的测试仍应在同一条
CI 中独立运行。原生布局、生命周期、无障碍、截图和真机 Capability 继续由三端集成
测试负责，不能用控制台行为用例替代。

## 上线前必须复核

1. 根据 UI 提示恢复正确的页面层级。
2. 确认状态类型、持久化 ID、脱敏默认值和生命周期。
3. 处理全部未选择或有歧义的本地依赖，以及所有人工复核项。
4. 只批准需要的 Capability，并补齐权限和隐私声明。
5. 使用同一组行为测试对比老页面与 PVM 页面。
6. 为每个平台和 Profile 分别编译、签名模块。
7. 在 CI 中强制检查 `verification.json` 的结果为 `"verified"`。

选择器和生成逻辑的快速回归命令：

```bash
make migration-check
```
