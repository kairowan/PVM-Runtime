[简体中文](PERFORMANCE.zh-CN.md)

# Rendering performance and large-page integration

PVM's performance goal is to prevent business-state updates from occupying the
UI thread with repeated full native-tree rebuilds without adding noticeable
latency to ordinary small pages. The runtime cannot promise a fixed frame rate
independent of the device, OS, and product NativeSurfaces; the target app must
define its frame-time SLO on its supported low-end hardware.
PVM ultimately calls platform-native controls, so it cannot promise to beat
optimized native code that already updates only the necessary leaf on every
page. It can beat common full-rebind implementations through compiler-stable
IDs, a shared incremental protocol, and default list virtualization without
requiring every product screen to hand-write its own diff.

## Implemented protection path

An event passes through the C++ VM, UI batch, platform model, and native views.
The current implementation bounds UI-thread work at five points:

1. **Shared VM deduplication and exact changes:** the C++17 runtime assigns a
   monotonic `revision` to every node. An unchanged snapshot produces no JSON,
   bridge call, or renderer invocation. A changed batch also carries exact
   `changed` node IDs and a `structureChanged` marker; first render and structural
   changes safely fall back to full reconciliation.
2. **Adaptive decoding with latest-batch backpressure:** the default Android,
   iOS UIKit/SwiftUI, and HarmonyOS hosts keep batches up to 32 KiB on the
   synchronous fast path. Larger JSON batches are decoded off the UI thread.
   If updates arrive while decoding, only the newest batch may be committed.
   HarmonyOS uses the system task pool and rejects late results after close.
3. **Direct main-thread commit by ID:** when structure is stable, Android View
   and UIKit directly update exact `changed` controls; SwiftUI synchronizes
   input state only for changed nodes; ArkUI builds ID paths during the first
   structural commit and later performs indexed in-place model updates instead
   of scanning the tree to find one node. Input focus and selection remain in
   place. Android's structural fallback also uses an O(n) stable-order fast
   path instead of repeated O(n²) searches.
4. **Stable-ID native reuse:** Android View and UIKit reuse controls by
   `node.id + node.type`, so ordinary changes do not recreate NativeSurfaces.
   SwiftUI gates subtrees by `node.id + revision`; HarmonyOS likewise reuses
   stable `PvmRenderedNode` IDs/revisions.
5. **Platform-native list virtualization and incremental updates:** DSL `List`
   maps to `RecyclerView + ListAdapter/DiffUtil` in Android Views,
   `UICollectionView + Diffable Data Source + Compositional List` in UIKit,
   native lazy `List` in SwiftUI, and
   `List + Repeat.virtualScroll(reusable: true)` on ArkUI API 23.
   Only visible items need native views; Android calculates list diffs in the
   background, UIKit updates stable-ID snapshots, and ArkUI reuses visible
   components.
   Fixed small structures continue to use `Row`, `Column`, and `Stack` without
   adapter overhead.

The Android AAR host intentionally targets existing View applications, so its
backend uses `RecyclerView`. If the currently incomplete Compose/CMP renderer
becomes a production backend, its `List` should map separately to `LazyColumn`;
existing hosts should not be forced to adopt Compose merely to run PVM.

`tests/test_e2e.py` compiles a page with 900 static nodes and executes 64
unchanged renders through the C ABI. The UI batch count must remain unchanged.
This is a deterministic regression gate, not a substitute for device profiling.
Android's `AndroidViewRendererListTest` also creates 1,000 rows on a device,
asserts that a half-screen viewport attaches only visible rows, and verifies
that changing one sibling does not rebind an unchanged NativeSurface.

`AndroidViewRendererPerformanceTest` compares three commit paths on the same
main thread and the same 240 existing TextViews. A 2026-07-31 Debug
instrumentation run on HONOR BRP-AN00 (Android 15/API 35) produced the following
microsecond results. Model construction and wire decoding are excluded, so this
measures native commit cost rather than end-to-end frame time:

| Path | p50 | p95 |
|---|---:|---:|
| PVM exact-changed commit | 72–75 | 172–187 |
| Native traversal and full rebind of 240 nodes | 108–118 | 274–290 |
| Optimized native update of one known leaf | 4 | 6–7 |

Across three reruns, PVM's paired p95 was about 35%–39% below the full native
rebind, while the optimized native leaf update remained the substantially lower
theoretical reference. This proves that the default incremental path beats full
rebind in this scenario—not that PVM universally beats native. Rerun it on a
connected Android device:

```bash
make android-render-benchmark
```

The gate requires PVM p95 to beat the paired full rebind and remain below
16.667 ms. Raw JSON is captured in Gradle's generated test logcat file.
End-to-end startup, scrolling, and animation still require Android
Macrobenchmark/Perfetto on a release or profileable build.

`PVMRendererPerformanceTests` covers both UIKit native-view commits and SwiftUI
state-tree commits on the same iOS Simulator main thread. On 2026-07-31, an
iPhone 17 Pro Max iOS 26.2 Simulator produced these 240-node, 180-sample
results. JSON decoding and model construction are excluded, so these are not
physical-iPhone frame-time results:

| Path | p50 | p95 |
|---|---:|---:|
| UIKit PVM Wire v2 patch commit | 5 μs | 7 μs |
| UIKit full rebind of 240 existing UILabels | 75 μs | 80 μs |
| UIKit optimized known-leaf update | 1 μs | 1 μs |
| SwiftUI Wire v2 ancestor-path merge | 4 μs | 6 μs |
| SwiftUI full-tree state bookkeeping | 209 μs | 233 μs |

Boot one iOS Simulator and rerun:

```bash
make ios-render-benchmark
```

The executable HarmonyOS gate transpiles and runs the repository's
`ArkUiRenderer.ets`. After a 240-node initial tree, a single-leaf batch must
update exactly one `PvmRenderedNode`, create no node, preserve the latest event
sink, coalesce queued decoding to the newest batch, reject late close results,
and surface decoding failure. In two Wire v2 runs using a Node host with DevEco
TypeScript, exact commit p95 was about 1–3 μs versus about 3–9 μs for simulated
full rebind. This is an algorithm regression gate, not ArkUI device layout or
drawing evidence:

```bash
make harmony-render-benchmark
```

## Rules for large products

- Keep node IDs unique within a page and stable across renders. Array indexes,
  timestamps, and random values prevent native-view reuse.
- Use `List` for unbounded collections. Do not expand hundreds of data rows into
  a `Column`; `Column` is for fixed forms and page structure.
- `List` is already a scrolling viewport; do not nest it in `Scroll`. An
  unbounded outer measurement defeats virtualization. Keep bounded headers and
  filters as siblings of the `List`.
- Split very large domains into pages or state-selected subtrees.
  `max_ui_nodes` is a safety limit, not a recommended per-frame size.
- Put network, database, image decoding, and vendor SDK work behind asynchronous
  capabilities. Synchronous capabilities must be strictly bounded.
- Update only necessary state on input. Debounce search, suggestions, and remote
  validation before invoking an asynchronous capability.
- A NativeSurface must manage its own image cache, map/player reuse, and
  background processing. PVM controls the container lifecycle, not the internal
  performance of a commercial component.

## Physical-device acceptance

Profile at least the lowest-end supported device under cold first render, fast
maximum-list scrolling, continuous input, bursty async completions, and
background/foreground restoration. Useful gates include:

- p50/p95 time from `dispatch` to the first visible UI update;
- counts of UI-thread tasks exceeding 16.7 ms and 50 ms;
- committed UI batches during bursty updates;
- native rows created for the first list viewport and peak scrolling memory;
- comparison with and without product NativeSurfaces.

Use Perfetto/JankStats on Android, Instruments Time Profiler and Core Animation
on iOS, and DevEco Profiler on HarmonyOS. Product device and UX requirements set
the threshold; desktop CI timing is not mobile-device evidence.

## Remaining boundary

A changed neutral snapshot is still evaluated in the VM in proportion to page
node count. Mobile hosts opt into C ABI v4 / UI Wire v2: structural changes send
a complete `root`, while stable structures send root identity/revision,
changed-node subtrees, and ancestor revisions only. C ABI v1–v3 stays on the
complete-root wire for binary and source compatibility. Ordinary non-list
native layout must still run on the UI thread. Deduplication, patch decode,
latest-batch backpressure, exact commit, reuse, and list virtualization remove
common duplicate work but cannot make an unbounded page constant-cost. The
remaining shared-runtime optimization boundary is incremental snapshot
evaluation; it must be driven by supported low-end-device evidence rather than
desktop microbenchmarks.
