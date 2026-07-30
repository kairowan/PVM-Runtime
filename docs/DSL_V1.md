# DSL 与字节码 v1/v2/v3/v4/v5

PVM DSL 当前使用 JSON 作为确定性语法载体。JSON 只是构建输入格式；客户端不会解释 JSON，生产模块只包含紧凑的私有 PVBC 表与指令。

完整示例见 [`server/sample/counter.pvm.json`](../server/sample/counter.pvm.json)。

## 顶层结构

```json
{
  "module": {},
  "delivery": {},
  "state": {},
  "handlers": {},
  "pages": {}
}
```

| 区域 | 作用 |
|---|---|
| `module` | App/租户/渠道/release、能力、最低版本、域名、存储和预算 |
| `delivery` | 目标平台与交付 Profile |
| `state` | 静态类型、初始值与持久化身份 |
| `handlers` | 栈式逻辑指令与 Effect |
| `pages` | 中立 UI Tree、模板属性和事件 |

## 模块声明

最小生产形状：

```json
{
  "module": {
    "id": "counter.home",
    "application_id": "com.example.protected",
    "tenant": "demo",
    "channel": "enterprise",
    "release": 5,
    "key_version": 1,
    "minimum_runtime": 5,
    "entry_page": "main",
    "capabilities": ["storage.kv", "ui.toast"],
    "capability_versions": {
      "storage.kv": 1,
      "ui.toast": 1
    },
    "network_domains": [],
    "storage_scopes": ["app.preferences"],
    "budget": {
      "max_instructions_per_event": 1000,
      "max_stack": 32,
      "max_state_bytes": 4096,
      "max_ui_nodes": 100,
      "max_tasks": 8
    }
  }
}
```

关键约束：

- `application_id`、`channel`、`id` 和 `tenant` 必须是安全路径标识符。
- `release` 必须为正整数，并且发布时严格大于仓库当前 release。
- `minimum_runtime` 不能小于目标 PVBC 格式，也不能大于当前编译器/Runtime。
- Capability 必须唯一、已声明，并存在于 [`spec/host_idl.json`](../spec/host_idl.json)。
- 使用网络 Capability 时必须声明 `network_domains`。
- 使用存储 Capability 时必须声明 `storage_scopes`。
- Runtime 会再次对所有预算应用硬上限。

## Delivery Profile

```json
{
  "delivery": {
    "profile": "online_provisioned",
    "platform": "android",
    "fallback_ui": true,
    "startup_dependencies_bundled": false,
    "native_dynamic_download": false,
    "external_code_artifacts": []
  }
}
```

支持的平台为 `android`、`ios`、`harmonyos` 和用于参考工具的 `desktop`。

支持四种 Profile：

- `offline_sealed`
- `online_provisioned`
- `store_on_demand`
- `enterprise_managed`

编译器会拒绝互相冲突的声明：

- Offline 必须包含全部启动依赖。
- Online Provisioned 必须有宿主 fallback UI。
- iOS Store On-Demand 不能声明 native 动态下载。
- Android Store On-Demand 不能声明外部 `.dex`、`.jar` 或 `.so`。

iOS 产品默认建议选择 `offline_sealed`。在线签名字节码是否可用必须针对实际产品按
[Apple App Review Guidelines 2.5.2](https://developer.apple.com/app-store/review/guidelines/)
审核；语言受限、模块签名和 Profile 校验本身都不是合规结论。

## 状态

支持三种静态类型：

| DSL 类型 | Runtime 类型 | 持久化编码 |
|---|---|---|
| `int` | 有符号 64 位整数 | little-endian 64-bit |
| `bool` | 布尔值 | 0 或 1 |
| `string` | UTF-8 字符串 | 长度 + 字节 |

PVBC v4 要求每个字段显式声明稳定 `persistence_id`：

```json
{
  "state": {
    "count": {
      "type": "int",
      "persistence_id": "count",
      "initial": 0
    },
    "status": {
      "type": "string",
      "persistence_id": "status",
      "initial": "Ready"
    }
  }
}
```

### 状态迁移

字段改名时保留原 `persistence_id`：

```json
{
  "total": {
    "type": "int",
    "persistence_id": "count",
    "initial": 0
  }
}
```

迁移规则：

- 匹配的 ID 与类型：恢复旧值。
- 新 ID：使用 `initial`。
- 旧快照中不存在于新模块的 ID：忽略。
- 相同 ID 但类型变化：拒绝恢复。
- `persistence_id` 重复、为空或不安全：编译失败。
- 非空快照没有任何匹配字段：拒绝恢复。

`persistence_id` 是持久合同。不要因为变量重命名而自动批量替换它。

## UI Tree

示例：

```json
{
  "pages": {
    "main": {
      "type": "column",
      "id": "counter_root",
      "props": {
        "accessibility_label": "Counter"
      },
      "children": [
        {
          "type": "text",
          "id": "counter_value",
          "props": {
            "text": "Total: {count}",
            "accessibility_label": "Current total {count}"
          }
        },
        {
          "type": "button",
          "id": "counter_increment",
          "props": {"text": "Increment"},
          "events": {"tap": "increment"}
        }
      ]
    }
  }
}
```

### 节点

`text`、`image`、`row`、`column`、`stack`、`scroll`、`list`、`button`、`input`、`switch`、`native_surface`。

### 属性

`text`、`source`、`accessibility_label`、`enabled`、`value`、`surface_type`。

属性允许用 `{stateName}` 插入只读状态；编译器会把模板拆成常量和状态槽，不保留模板源码。

### 事件

`tap`、`change`、`submit`、`appear`。

每个源码 `id` 生成稳定 FNV-1a 32 位数值节点 ID。源码 ID 不进入模块，编译器拒绝 Hash 冲突。

PVBC v5 的 `change`/`submit` 可以携带宿主控件值。处理器通过 `event.value` 读取字符串：

```json
{
  "set_name": [
    {"op": "event.value"},
    {"op": "state.set", "name": "name"},
    {"op": "render", "page": "main"}
  ]
}
```

Android View、UIKit/SwiftUI 与 HarmonyOS ArkUI 合同会转发 Input 文本或 Switch 的
`"true"`/`"false"`。没有值的事件执行 `event.value` 会失败；输入值也受
`max_state_bytes` 限制。Compose/CMP 与 Kuikly 代码目前只是未进入产品构建的原型。

`appear` 的合同是 absent→present：同一节点 ID 连续存在于整树 replace 批次时只触发
一次；从树中移除后再次加入，才可再次触发。

## 处理器与指令

```json
{
  "handlers": {
    "increment": [
      {"op": "state.get", "name": "count"},
      {"op": "const", "value": 1},
      {"op": "int.add"},
      {"op": "state.set", "name": "count"},
      {"op": "render", "page": "main"}
    ]
  }
}
```

| 指令 | 栈效果 |
|---|---|
| `const` | 推入 `int`、`bool` 或 `string` |
| `event.value` | 推入当前 UI 事件携带的 `string`；需要 PVBC v5 |
| `state.get` | 推入指定状态值 |
| `state.set` | 弹出与状态相同类型的值 |
| `int.add` | 弹出两个 `int`，检查溢出后推入结果 |
| `equal` | 弹出两个同类型值，推入 `bool` |
| `jump` | 跳到指令序号 |
| `jump_if_false` | 弹出 `bool`，为假时跳转 |
| `effect` | 弹出参数，同步调用 Capability，推入 `string` |
| `effect.async` | 弹出参数并保存 continuation，完成后推入 `string` |
| `pop` | 丢弃栈顶 |
| `render` | 输出指定页面 |
| `halt` | 结束；未显式写出时编译器自动补齐 |

编译器使用工作队列验证所有可达控制流：

- 栈不能下溢。
- `state.set`、`int.add`、`jump_if_false` 必须使用正确类型。
- 两条分支汇合时栈形状必须一致。
- 跳转必须留在当前处理器。
- `halt` 时栈必须为空。
- Effect 只能调用已声明 Capability，参数数目必须与 Host IDL 一致。

Runtime 在加载时重复执行独立验证，避免信任编译器输出。

## 异步 Effect

`effect.async` 从 PVBC v2 开始支持。VM 保存 continuation 和 64 位任务 ID，宿主完成后调用 `pvm_runtime_complete_effect`。页面或进程生命周期结束时调用 `pvm_runtime_cancel_all_tasks`。

异步结果当前统一为 `string`，并受状态/结果大小与 `max_tasks` 约束。取消会删除
continuation；Android/iOS/HarmonyOS Host 在 cancel/close 后丢弃迟到回调，不能让
已取消任务或已销毁 Runtime 重新进入执行。

## 包格式

`.pvm` 外层：

```text
PVMP
  package format = 1
  signature algorithm = Ed25519
  payload length
  signature length = 64
  PVBC payload
  signature
```

PVBC 包含绑定元数据、预算、Capability/域名/存储表、常量池、状态、处理器、UI 节点和入口点。签名覆盖完整 payload。

## 版本演进

| PVBC | 新增能力 | Runtime 5 行为 |
|---|---|---|
| v1 | 同步 Effect、UI、状态与预算 | 兼容读取 |
| v2 | `effect.async`、`max_tasks` | 兼容读取 |
| v3 | Capability 最低版本 | 兼容读取 |
| v4 | 稳定状态持久化 ID与迁移快照 | 兼容读取 |
| v5 | `event.value` 输入/开关值回传 | 默认输出 |

历史兼容矩阵覆盖五个业务域 × v1/v2/v3。v4/v5 由主端到端、状态迁移、输入事件、三端交付和 fuzz 门禁覆盖。

## 构建命令

Lint：

```bash
PYTHONPATH=server/src python3 -m pvm_server.tooling lint \
  server/sample/counter.pvm.json
```

编译：

```bash
PYTHONPATH=server/src python3 -m pvm_server.compiler \
  server/sample/counter.pvm.json \
  --private-key server/var/keys/dev-private.pem \
  --output build/counter.pvm
```

指定历史格式：

```bash
PYTHONPATH=server/src python3 -m pvm_server.compiler \
  path/to/module.json \
  --format-version 3 \
  --private-key server/var/keys/dev-private.pem \
  --output build/module-v3.pvm
```

`minimum_runtime` 必须与选择的格式相容。生产构建应使用远程 signer，而不是本地私钥。

## 当前语言边界

当前 DSL 是锁定 VM、安全交付和三端宿主语义的最小语言，不是附件中完整语言愿景的全部实现。尚未加入记录、集合、泛型、模式匹配、结构化异常、超时/重试和模块依赖系统；这些能力应在真实业务需求与兼容策略明确后逐项演进，而不是扩张成任意系统编程语言。
