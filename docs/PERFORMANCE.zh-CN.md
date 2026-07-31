[English](PERFORMANCE.md)

# 渲染性能与大页面接入

PVM 的性能目标是：业务状态更新不能通过重复整树重建长期占用 UI 线程，普通小页面也
不应为了大页面优化而增加可感知延迟。Runtime 不承诺脱离具体设备、系统版本和业务
NativeSurface 的固定帧率；目标 App 必须在自己的最低端设备上建立帧时间 SLO。
PVM 最终仍调用平台原生控件，因此不能保证在所有页面上快过已经只更新必要叶子节点的
优化原生代码；它可以通过编译期稳定 ID、统一差量协议和默认虚拟化，快过每次全量
重绑的常见实现，并让业务无需为每个页面重复手写差量逻辑。

## 已实现的保护路径

一次事件更新依次经过 C++ VM、UI 批次、平台模型和原生控件。当前实现从五个位置限制
主线程工作：

1. **共享 VM 去重与精确变更协议**：C++17 Runtime 为每个节点计算单调 `revision`。
   整棵 Snapshot 不变时，不再生成 JSON、不跨 JNI/Objective-C/NAPI，也不调用
   Renderer；有变化时，批次同时携带精确 `changed` 节点和
   `structureChanged` 标记。初次渲染或结构变化安全回退为完整协调。
2. **自适应解析与最新批次背压**：Android、iOS 的 UIKit/SwiftUI 和 HarmonyOS 默认 Host 对
   32 KiB 以内的小批次保持同步快路径；更大的 JSON 在专用任务中解析。解析期间发生
   多次更新时只提交最新批次，旧结果不能覆盖新状态。HarmonyOS 使用系统 `taskpool`
   执行解析，并在关闭 Session 后拒绝迟到结果。
3. **主线程按 ID 直接提交**：无结构变化时，Android View 和 UIKit 直接找到
   `changed` 对应控件；SwiftUI 只同步变化节点的输入值；ArkUI 在首次结构提交时建立
   ID 路径索引，后续直接定位并原位更新本地模型，不再为找一个节点遍历整棵树。Input
   的焦点与选择区保持不变。Android 普通容器的结构回退路径也使用稳定顺序 O(n)
   快路，而不是重复线性查找形成 O(n²)。
4. **稳定 ID 原生复用**：Android View 和 UIKit 按 `node.id + node.type` 复用已有控件；
   NativeSurface 不再因普通状态更新被销毁。SwiftUI 以 `node.id + revision` 建立
   Equatable 子树门，HarmonyOS 的 `PvmRenderedNode` 同样复用稳定 ID/revision。
5. **按平台的大列表虚拟化与差量更新**：DSL `List` 在 Android View 使用
   `RecyclerView + ListAdapter/DiffUtil`，在 UIKit 使用
   `UICollectionView + Diffable Data Source + Compositional List`，在 SwiftUI 使用
   原生惰性 `List`，在 ArkUI API 23 使用
   `List + Repeat.virtualScroll(reusable: true)`。只有可见项需要原生视图；Android
   的列表差量在后台计算，UIKit 通过稳定 ID Snapshot 更新，ArkUI 复用可见组件。
   有限、固定的小布局仍使用 `Row`、`Column` 和 `Stack`，不承担列表 Adapter 开销。

Android 这里明确是面向已有 View 工程的 AAR Host，因此使用 `RecyclerView`；若后续把
当前尚未编译完成的 Compose/CMP Renderer 做成正式后端，其 `List` 应单独映射为
`LazyColumn`，而不是强制老项目为了运行 PVM 引入 Compose。

`tests/test_e2e.py` 会编译一棵包含 900 个静态节点的页面，并通过 C ABI 连续执行 64 次
输出不变的渲染；门禁要求 UI 批次数保持不变。这是确定性退化检查，不代替真机帧测试。
Android 的 `AndroidViewRendererListTest` 还会在设备上构造 1000 行列表，并断言半屏
视口只挂载可见行，同时验证只变化一个兄弟节点不会重绑 NativeSurface。

`AndroidViewRendererPerformanceTest` 在同一主线程、同一组 240 个既有 TextView 上
比较三条提交路径。2026-07-31 在 HONOR BRP-AN00（Android 15/API 35）的 Debug
仪器测试结果如下；单位为微秒，排除了模型构造和 Wire Decode，只代表原生提交成本：

| 路径 | p50 | p95 |
|---|---:|---:|
| PVM 精确 changed 提交 | 72–75 | 172–187 |
| 原生遍历并全量重绑 240 个节点 | 108–118 | 274–290 |
| 已知目标后由原生直接改一个叶子 | 4 | 6–7 |

三次复跑中 PVM p95 比配对的全量原生重绑低约 35%–39%，但优化原生叶子更新仍是
明显更低的理论对照。
因此该结果证明“默认差量优于全量重绑”，不证明 PVM 在所有页面上普遍快过原生。
连接 Android 真机后可重跑：

```bash
make android-render-benchmark
```

门禁要求 PVM p95 低于对应全量重绑且低于 16.667 ms；原始 JSON 保存在 Gradle 生成的
测试 logcat 文件中。端到端首帧、滚动和动画仍应使用 Android Macrobenchmark/Perfetto
在 Release/可分析构建上测量。

iOS 的 `PVMRendererPerformanceTests` 在同一个 iOS Simulator 主线程上分别覆盖 UIKit
原生控件提交与 SwiftUI 状态树提交。2026-07-31 在 iPhone 17 Pro Max、iOS 26.2
Simulator 的 240 节点、180 次样本结果如下；同样排除了 JSON Decode 与模型构造，
因此不能当作 iPhone 真机帧时间：

| 路径 | p50 | p95 |
|---|---:|---:|
| UIKit PVM Wire v2 补丁提交 | 5 μs | 7 μs |
| UIKit 全量重绑 240 个既有 UILabel | 75 μs | 80 μs |
| UIKit 已知目标后的单叶子更新 | 1 μs | 1 μs |
| SwiftUI Wire v2 祖先路径合并 | 4 μs | 6 μs |
| SwiftUI 全树状态簿记 | 209 μs | 233 μs |

启动一个 iOS Simulator 后可重跑：

```bash
make ios-render-benchmark
```

HarmonyOS 的可执行门禁直接转译并运行仓库中的 `ArkUiRenderer.ets`：初次建立 240
节点后，单叶子批次必须只更新一个 `PvmRenderedNode`、创建零个新节点，并验证最新
批次背压、关闭后迟到结果和解析失败路径。使用 DevEco TypeScript 的 Node Host 提交
回归中，两次 Wire v2 运行的精确路径 p95 约 1–3 μs、模拟全量重绑 p95 约 3–9 μs；
该数值只用于发现算法退化，不代表 ArkUI 真机布局或绘制耗时。可运行：

```bash
make harmony-render-benchmark
```

## 大项目的页面规则

- 节点 ID 必须稳定且在页面内唯一。不要把数组下标、时间戳或随机数作为长期 ID，否则
  Renderer 无法复用原生控件。
- 不受控的数据集合必须使用 `List`。不要把数百个数据行展开到 `Column`；`Column`
  适合数量固定的表单和页面骨架。
- `List` 自身就是滚动视口，不要再放进 `Scroll`。外层无界测量会破坏列表虚拟化；
  固定标题、筛选栏等应作为与 `List` 同级的有限节点。
- 将巨大业务域拆成多个页面或按状态选择的子树。`max_ui_nodes` 是安全上限，不是建议
  每帧使用的节点数。
- 网络、数据库、图片解码和商业 SDK 调用放进异步 Capability。同步 Capability 只做
  有严格上限的内存操作；它会延长当前事件处理时间。
- 输入事件只更新必要状态。搜索、联想和远端校验应防抖后走异步 Capability，不能在每个
  `change` 事件里执行大遍历。
- NativeSurface 内部自行使用平台的图片缓存、地图/播放器复用和后台数据处理；PVM
  只能保证 Surface 容器的生命周期，不能替代商业组件自身的性能治理。

## 真机验收

至少选择目标产品支持范围内的最低端设备，分别记录冷启动首屏、最大列表快速滚动、
连续输入、异步结果集中返回和前后台恢复。建议门禁包含：

- `dispatch` 到首个可见 UI 更新的 p50/p95；
- 主线程超过 16.7 ms 和 50 ms 的任务数量；
- 快速更新时实际提交的 UI 批次数；
- 列表首屏创建的原生行数和滚动期间的内存峰值；
- NativeSurface 存在与不存在时的对照结果。

Android 使用 Perfetto/JankStats，iOS 使用 Instruments 的 Time Profiler 与 Core
Animation，HarmonyOS 使用 DevEco Profiler。通过门槛应由目标 App 的设备矩阵和业务
体验确定，不应把桌面 CI 的耗时直接当作移动端结论。

## 仍然需要注意的边界

变化后的中立 Snapshot 仍需在 VM 内按页面节点数求值。移动端 Host 使用 C ABI v4 /
UI Wire v2：结构变化发送完整 `root`；结构稳定时只发送 Root identity/revision、变化
节点子树和祖先 revision。C ABI v1–v3 为二进制与源码兼容继续使用完整树 Wire。
普通非列表容器仍必须由 UI 线程完成必要的原生布局。去重、补丁解析、最新批次背压、
精确提交、复用和列表虚拟化消除了最常见的重复工作，但不能让无限大的单页成为常数
成本。共享 Runtime 剩余的优化边界是 Snapshot 的增量求值，应由支持矩阵中的低端真机
数据决定，不能用桌面微基准代替。
