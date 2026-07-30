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
| C ABI v3 five-way binding | Implemented | C ABI smoke and platform hosts |
| create/restore/start/dispatch/cancel lifecycle | Implemented | negative lifecycle tests |
| sync/async effects and cancellation | Implemented | C ABI and task-budget tests |
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
| Android View | 11 nodes, properties, four events, values, NativeSurface factory, appear semantics | image policy, style, performance, broad devices |
| Android Compose/CMP | shared KMP call layer builds | recursive Compose tree and product-version integration |
| UIKit | 11 nodes, stack constraints, events, values, NativeSurface | images, complex layout/reuse, device calibration |
| SwiftUI | recursive tree, inputs, switch, events, accessibility, appear | NativeSurface, images, complex lists |
| ArkUI | compiled recursive native tree and event semantics | complex layout performance, NativeSurface, broad devices |
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
