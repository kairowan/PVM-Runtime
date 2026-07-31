[简体中文](FUNCTIONAL_STATUS.zh-CN.md)

# Functional status

“Implemented” means runnable repository code, not a type declaration, interface
placeholder, or adapter that a target app still needs to write. Compilation
proves compatibility with the current SDK headers; it does not replace physical
device acceptance.

## Core path

| Capability | Status | Runnable evidence |
|---|---|---|
| DSL types, control flow, budgets | Implemented | `make test` |
| PVBC v1–v5, signature, binding, rollback | Implemented | `make test compatibility` |
| C ABI v4 five-way binding and UI Wire v2 patches | Implemented | v1/v3 compatibility plus v4 patch C ABI smoke and platform hosts |
| create/restore/start/dispatch/cancel lifecycle | Implemented | negative lifecycle tests |
| sync/async effects and cancellation | Implemented | C ABI and task-budget tests |
| per-node revisions, exact changed IDs, structural fallback | Implemented | C ABI plus Android device, iOS Simulator, and Harmony host regression gates |
| v4 stable state migration | Implemented | rename/add/conflict tests |
| v5 input/switch values | Implemented | `event.value` regression |
| manifest/download/hash/preload/atomic LKG | Implemented | HTTP/LKG and Module Stores |
| strict platform LKG state | Implemented | `make test platform-check` |
| Android SDK/demo/APK/AAB/AAR/Maven | Implemented | `make android-demo-check` |
| iOS Package/Host/Privacy/XCFramework/demo | Implemented | iOS SDK and demo gates |
| HarmonyOS HAR/unsigned HAP/two ABIs | Implemented | `make harmony-sdk-check` |
| KMP common/JVM/iOS/Maven | Implemented | KMP gates |
| Precompiled three-platform SDK release set | Implemented | `make sdk-release-assets` |
| Release-signed APK/AAB, IPA, HAP | Target app | organization credentials required |

## Android product baseline

| Item | Current state | Boundary |
|---|---|---|
| Build | AGP 9.3.1, Gradle 9.6.1, built-in Kotlin 2.4.10 | library and demo modules |
| SDK | compile/target 36, NDK 28 | Runtime min 24; demo min 33 |
| ABI | arm64-v8a and x86_64 | checked in AAR/APK/AAB |
| 16 KiB | ELF and ZIP alignment checks | artifact checker |
| Distribution | release AAR and local Maven | `pvm-runtime:0.5.0` |
| Demo | debug APK/AAB and minified R8 smoke APK | development/test signing |
| Device | HONOR BRP-AN00, API 35 | one-device smoke only |

## Renderers

| Backend | Available | Remaining |
|---|---|---|
| Android View | 11 nodes, exact changed-ID commits, stable-ID reuse, `RecyclerView + ListAdapter/DiffUtil`, adaptive decode/backpressure, values, NativeSurface and appear; on HONOR API 35, a 1,000-row viewport gate passes and a 240-node single-leaf commit measured 172–187 μs p95, about 35%–39% below paired full rebind | release Macrobenchmark/scroll frame and memory SLOs, images, styling and broad devices |
| Android Compose/CMP | shared KMP call layer builds | recursive Compose tree and product-version integration |
| UIKit | 11 nodes, Wire v2 exact changed-ID commits, stable-ID reuse, compositional diffable `UICollectionView`, adaptive decode/backpressure, values and NativeSurface; 240-node Simulator patch commit p95 7 μs | physical-device Instruments/list SLOs, images and product layouts |
| SwiftUI | `node.id + revision` Equatable subtree gates, Wire v2 stable-path ancestor merge, native lazy `List`, adaptive decode/backpressure, inputs, events and accessibility; 240-node Simulator patch merge p95 6 μs | NativeSurface, physical-device Instruments, images and product styling |
| ArkUI | Wire v2 stable-ID/path-index exact updates, 32 KiB task-pool decode with latest-batch backpressure, `List + Repeat.virtualScroll(reusable: true)`, native tree and event semantics | large-list physical-device SLOs, NativeSurface and broad devices |
| Kuikly | unbuilt port prototype | select only if a product adopts a pinned SDK |

Machine-readable backend status lives in
[`spec/renderer_conformance.json`](../spec/renderer_conformance.json).

## Capabilities

[`spec/host_idl.json`](../spec/host_idl.json) declares 27 versioned
capabilities. A declared contract is not an installed adapter.

| Host | Concrete repository adapters |
|---|---|
| Android | `ui.toast`, `storage.kv`, `network.http`, `push.inbox`, `permission.request` |
| iOS | `ui.toast`, `storage.kv`, `network.http`, `push.inbox` |
| HarmonyOS | basic `ui.toast` and `storage.kv` |

The remaining contracts—including background, biometric, Bluetooth, camera,
database, files, location, maps, media, microphone, transfer/WebSocket, NFC,
notification, payment, QR, secure keystore, sharing, extensions, and telemetry—
require target-app or vendor adapters. Native components `camera.preview`,
`host.screen`, `map.view`, and `player.view` require renderer NativeSurface
factories.

## Remaining core phases

1. **HarmonyOS production completion:** HUKS, online Module Store, capability
   adapters, commercial/AppGallery signing, and broader physical devices.
2. **KMP/CMP product integration:** platform actual runtime and selected Compose
   host; Kuikly only when explicitly required.
3. **Production acceptance and operations:** iOS physical archive/distribution,
   release-signed platform packages, device matrices, business capabilities,
   HSM/KMS, production auth/audit/alerts, performance, stores, billing, and red
   team.

See [Delivery status](DELIVERY_STATUS.md) and
[Platform integration](PLATFORM_INTEGRATION.md).
