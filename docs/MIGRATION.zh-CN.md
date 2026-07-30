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
├── capabilities.json       尚未批准的 Host Capability 建议
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

## 上线前必须复核

1. 根据 UI 提示恢复正确的页面层级。
2. 确认状态类型、持久化 ID、脱敏默认值和生命周期。
3. 处理全部未选择或有歧义的本地依赖，以及所有人工复核项。
4. 只批准需要的 Capability，并补齐权限和隐私声明。
5. 使用同一组行为测试对比老页面与 PVM 页面。
6. 为每个平台和 Profile 分别编译、签名模块。

选择器和生成逻辑的快速回归命令：

```bash
make migration-check
```
