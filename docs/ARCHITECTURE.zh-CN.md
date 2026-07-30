[English](ARCHITECTURE.md)

# 架构与数据流

PVM Runtime 把“业务表达”“安全交付”和“平台能力”分开演进：DSL/字节码/VM 语义保持一致，Delivery Profile 只改变模块进入设备的方式，UI 与重能力继续由平台宿主负责。

![PVM Runtime system architecture](assets/system-architecture.svg)

## 设计原则

1. **先验证再执行**：签名正确只是入口条件，字节码仍按不可信输入完整验证。
2. **声明式业务不等于远程原生代码**：模块不能携带 DEX、SO、Framework 或任意平台调用。
3. **平台能力留在宿主**：支付、相机、地图、媒体帧和系统调度不进入 VM。
4. **交付策略与业务源码分离**：四种 Profile 使用同一 DSL 和 Runtime。
5. **失败时保住 LKG**：刷新不能覆盖已验证模块，运营回退不能削弱防回滚。
6. **兼容性显式版本化**：PVBC、Runtime、Host IDL、Capability 和状态都带版本或稳定身份。

## 三个信任平面

### Build Plane

| 组件 | 职责 |
|---|---|
| DSL source | 描述模块绑定、状态、页面、处理器、Effect、资源预算和交付 Profile |
| `compiler.py` | 语义/类型/控制流/Profile 检查，生成确定性 PVBC |
| `tooling.py` | 对照 Host IDL 验证 Capability、操作和参数 |
| signer | 对模块 payload 和 Manifest payload 进行 Ed25519 签名 |
| `delivery_build.py` | 从同一 DSL 生成三平台 × 四 Profile 产物 |

DSL 只存在于构建边界，不写入 `.pvm`。生产模块不包含状态源码名、处理器名、节点源码 ID、注释、源码路径或 source map。

### Delivery Plane

| 组件 | 职责 |
|---|---|
| `publish.py` | 原子写入内容寻址模块、访问策略、历史和签名 Manifest |
| immutable repository | 用 SHA-256 作为模块文件名，避免可变 URL 覆盖 |
| `serve.py` | 激活鉴权、ETag、Profile 访问控制、稳定灰度与审计 |
| `release.py` | 调整 rollout 或止血，不修改签名 release payload |

仓库键是：

```text
application_id / channel / platform / profile
```

application、channel、platform、profile 和 release 同时存在于 Manifest 与签名字节码
中，避免跨应用、跨渠道、跨平台或跨交付策略误加载。

### Device Plane

| 组件 | 职责 |
|---|---|
| Module Store | Manifest 验签、绑定、release floor、下载、Hash、预加载、原子缓存 |
| C++17 Runtime | 模块验签、字节码验证、解释执行、状态快照与 watchdog |
| UIHost | 把中立 UI Tree 映射到原生 Renderer，并回传事件 |
| Capability Host | 对版本、权限、线程、参数和用户授权再次检查后调用原生 SDK |

Android、iOS、HarmonyOS 共用同一 Runtime 和 C ABI，不复制解释器。新移动端 Host
使用 C ABI v3：创建时强制 application/channel/platform/profile 与 release floor，
Module Store 再要求 VM 返回的 release 等于签名 Manifest release。

## 从 DSL 到 UI 的数据流

```mermaid
sequenceDiagram
    participant DSL as DSL source
    participant Compiler as Compiler
    participant Signer as Signer/HSM
    participant Repo as Module repository
    participant Store as Device module store
    participant VM as C++17 VM
    participant Host as UI/Capability Host

    DSL->>Compiler: compile + policy/IDL checks
    Compiler->>Signer: deterministic PVBC payload
    Signer-->>Compiler: Ed25519 signature
    Compiler->>Repo: immutable .pvm
    Compiler->>Signer: canonical Manifest payload
    Signer-->>Repo: signed Manifest envelope
    Store->>Repo: GET Manifest + installation ID
    Repo-->>Store: selected signed envelope
    Store->>Store: verify signature/binding/release
    Store->>Repo: GET /v1/modules/&lt;sha256&gt;.pvm
    Repo-->>Store: immutable module
    Store->>VM: preload validation
    VM-->>Store: metadata + release
    Store->>Store: atomic LKG switch
    Store->>VM: start/restore
    VM->>Host: replace UI Tree
    Host->>VM: node event
    VM->>Host: typed Capability Effect
```

## 模块格式

### PVMP 容器

```text
magic "PVMP"
package version
signature algorithm
payload length
signature length
PVBC payload
Ed25519 signature
```

签名在解析 PVBC 业务表之前验证。模块包有 16 MiB 硬上限。

### PVBC payload

包含：

- 格式与最低 Runtime。
- release、key version、应用/租户/渠道/平台/Profile 绑定。
- 状态 Schema 和 v4 稳定持久化 ID。
- 资源预算。
- Capability 与最低版本、网络域名和存储范围。
- 常量池、状态初始值、处理器、UI 节点和入口点。

Runtime 5 读取 v1–v5；默认编译 v5。历史格式没有 Capability 版本时按 v1 处理。

## Manifest 与控制对象

签名 payload 只包含不可由运营随意修改的 release 描述。服务端仓库的 `manifest.json` 额外保存：

- 当前签名信封。
- 上一签名信封。
- rollout 百分比。

服务端先按稳定安装 ID 选择 current/previous，再只返回选中信封。客户端不信任服务端选择，但能验证选择出的 release 确实由发布密钥授权。

## 加载与原子更新

客户端更新顺序固定：

```text
signed Manifest
  → signature
  → application/channel/platform/profile/release binding
  → same-origin content-addressed URL
  → temporary download
  → size + SHA-256
  → module signature
  → runtime/bytecode/capability preload
  → atomic rename
  → atomic current state
  → remove cache entries outside two-version history
```

任何一步失败，临时文件都会删除，当前 LKG 保持不变。Android、iOS 与 HarmonyOS
的 `current` 状态格式都固定为 v1，并严格校验 application/channel/platform/profile、
正整数 release、当前 SHA-256、非空且最多两项的去重历史，以及“历史第一项等于当前
Hash”；绑定不匹配或损坏的状态不会成为 LKG。

## 状态生命周期

PVBC v4 为每个状态字段写入由 App、模块和 `persistence_id` 生成的不可逆 64 位 ID：

- 字段改名时保留 `persistence_id`，旧值继续恢复。
- 新字段找不到旧 ID 时使用初始值。
- 已删除字段被忽略。
- 相同 ID 的类型变化被拒绝。
- 非空快照至少匹配一个当前字段，避免把其他模块状态静默当作空迁移。

v1–v3 模块继续使用严格 Schema 相等恢复。

## Runtime 生命周期

Runtime 生命周期是显式状态机：

```text
created → optional restore → start (exactly once) → dispatch/complete/snapshot
                                             └── cancel pending tasks → destroy
```

- `dispatch` 和异步 `complete_effect` 在 start 前失败。
- `restore_state` 只能在 start 前执行；重复 start 被拒绝。
- cancel 清空 VM continuation；三端 Host 递增任务 generation 或解除回调持有，
  因而 cancel/close 后到达的原生异步结果会被丢弃，不能恢复已取消或已销毁的 VM。
- 平台 Host 的 close 是幂等终点；之后不再接受事件、状态或异步结果。

## UI 与 Capability 边界

VM 输出整批中立 UI Tree，节点只包含类型、稳定数值 ID、属性、事件和子节点。宿主：

- 在平台 UI 线程创建或更新原生控件。
- 把点击、输入、提交、出现等事件回传 VM；v5 change/submit 可携带受预算限制的字符串值。
- `appear` 只在节点从 absent 进入 present 时发送一次；仍存在于后续整树 replace 的节点
  不会重复发送，离开树后重新出现才可再次发送。
- 用 Native Surface 承载地图、播放器、相机预览等高频原生内容。
- 不让视频帧、相机帧或手势流穿过 VM。

Capability Registry 必须先应用模块元数据，再允许调用。模块未声明、宿主未安装或版本不足都应在启动或调用边界失败。

## 目录职责

```text
server/
  sample/                  可运行 DSL 与业务域样本
  src/pvm_server/
    compiler.py            DSL、静态检查、PVBC、模块签名
    manifest.py            canonical Manifest 与签名信封
    publish.py             内容寻址模块、历史与原子发布
    serve.py               鉴权、ETag、灰度、审计
    release.py             rollout 与止血
    host_idl.py            四端合同生成
    delivery_build.py      三平台 × 四 Profile
    compatibility.py       五业务域 × 历史字节码
client/
  include/pvm/             公共 C++/C ABI
  src/runtime.cpp          验签、验证器、解释器、状态迁移
  src/c_api.cpp            C ABI 与 JSON UI 批次
  tools/provision.py       桌面参考 Module Store
  platform/android/        Kotlin/JNI/Renderer/Module Store
  platform/ios/            Objective-C++/Swift/Renderer/Module Store
  platform/harmony/        DevEco 工程、Runtime HAR、Demo HAP、Node-API/ArkTS/ArkUI
spec/                      Host IDL、Renderer 与发布门禁合同
generated/                 生成的 Kotlin/Swift/ArkTS/C++ 接口
```

## 四种 Delivery Profile

![PVM Runtime delivery profiles](assets/delivery-profiles.svg)

Profile 只改变模块来源与打包约束。Android `Offline Sealed` 可嵌入 APK 或 AAB；前者适合直接安装、测试与部分企业分发，后者适合 Google Play。详细发布行为见[发布与运维](OPERATIONS.zh-CN.md)。

## 有意保留的边界

当前实现使用完整小模块和整树批量替换。只有真实页面规模和帧预算证明它成为瓶颈后，才应增加 Incremental Diff；不先引入未经需要证明的复杂协议。

仍需在具体产品环境完成：

- KeyStore/Keychain/HUKS 缓存密钥与平台完整性证明。
- 商业支付、地图、相机、媒体和推送 Adapter。
- iOS 真机、archive/Apple Distribution codesign 与审核证据；Simulator Demo 已提供。
- HarmonyOS 已有 DevEco API 24 工程、兼容 API 23 的 Runtime HAR 与 unsigned
  Emulator HAP，以及 arm64-v8a/x86_64 C++17 Node-API/ArkUI 构建；Huawei debug
  signed HAP 已在一台 HUAWEI Pura 70 完成交互和状态恢复。仍需 HUKS、线上 Module
  Store、完整 Capability、commercial/release/AppGallery 签名和更多物理设备证据。
- KMP commonMain/JVM/iOS 制品已经建立；目标项目仍需连接平台 actual Runtime 与选定
  版本的 Compose Host。Kuikly 只在产品需要时锁定版本并实现 Adapter。
- 正式 KMS/HSM、组织日志、应用市场审核、支付沙箱、红队和性能 SLO。

安全假设与剩余风险见[安全模型](SECURITY_MODEL.zh-CN.md)，当前证据见[交付状态](DELIVERY_STATUS.zh-CN.md)。
