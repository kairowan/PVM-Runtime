[简体中文](DELIVERY_STATUS.zh-CN.md)

# Delivery status and acceptance evidence

This document distinguishes:

- **Implemented in the repository:** real code and a runnable path exist.
- **Proven by automation:** a repeatable gate exists and currently passes.
- **External acceptance required:** evidence needs organization accounts,
  production infrastructure, commercial SDKs, or physical devices.

An engineering baseline is not a store, security, or production certification.

## Current version snapshot

| Item | Current state |
|---|---|
| Runtime / bytecode | Runtime 5; default PVBC v5; reads v1–v5 |
| Module / manifest signature | Ed25519; PVMP v1; signed manifest envelope v1 |
| Mobile C ABI | v3 with application/channel/platform/profile/release-floor binding |
| Platforms | Android, iOS, HarmonyOS, desktop reference host |
| Delivery profiles | Four; 3 platforms × 4 profiles = 12 embedding inputs |
| Android | Debug APK/AAB, R8 smoke APK, release AAR, local Maven |
| Android SDK | `com.protectedvm:pvm-runtime:0.5.0`; API 36; NDK 28; two ABIs |
| Android device evidence | HONOR BRP-AN00, API 35 interaction and restore |
| iOS | Source Package, `@MainActor PVMHost`, Privacy Manifest, complete binary XCFramework |
| iOS demo evidence | iPhone 17 Pro Max Simulator, iOS 26.2 |
| HarmonyOS | DevEco API 24/API 23-compatible HAR and unsigned emulator HAP |
| HarmonyOS device evidence | HUAWEI Pura 70, HarmonyOS 6.1, debug-signed HAP |
| KMP | commonMain/JVM/iOS Native; `pvm-runtime-kmp:0.5.0` |
| SDK release set | AAR/Maven, Binary Swift Package/XCFramework, HAR, SHA-256 inventory |
| Historical matrix | Five domains × PVBC v1/v2/v3 = 15 cases |
| Production packages | Produced by target apps with their release accounts |

## Capability status

| Area | Implemented | Automated evidence | External gap |
|---|---|---|---|
| DSL/compiler | State, pages, handlers, effects, event values, profile/IDL/budget checks | `make test verify-contracts` | IDE and production-scale languages |
| Module security | Deterministic PVBC, Ed25519, C ABI v3 bindings, rollback, verifier | `make test fuzz-check sanitizer-check` | sustained fuzzing and independent audit |
| State evolution | v4 stable IDs, rename/add migration, type-conflict rejection | migration end-to-end tests | product migration tooling |
| Delivery service | Addressing, policy, signed manifest, ETag, rollout, audit, TLS, health | HTTP/tamper/rollout/LKG tests | production CDN, identity, DB, HA |
| Android | Library/demo, JNI/View, Module Store, AAR/Maven, APK/AAB/R8 | `platform-check`, `android-demo-check`, HONOR smoke | Compose, broad lab, capabilities, store signing |
| iOS | Source Package, binary framework, host, UIKit/SwiftUI, Store, Privacy, demo | `ios-sdk-check`, `ios-demo-check`, simulator | physical device, archive, distribution, review |
| HarmonyOS | DevEco project, Node-API/ArkTS, ArkUI, HAR, offline HAP | `harmony-sdk-check`, Pura 70 smoke | HUKS, online Store, capabilities, commercial signing |
| KMP | Port, lifecycle/events, JVM and iOS targets, Maven | `kmp-check`, `kmp-packages` | platform actuals, chosen Compose host |
| Capability | 27 versioned contracts; basic adapters on each platform | `verify-contracts`, `platform-check` | vendor and remaining system adapters |
| Compatibility | Runtime v1–v5 reads and five-domain historical matrix | `compatibility`, `test` | long-lived production upgrade data |

## Android evidence

| Evidence | Result |
|---|---|
| Runtime | Release AAR with Kotlin host and complete C++17 VM |
| Demo | Debug APK and AAB |
| R8 | Minified, non-debuggable smoke APK |
| SDK | AAR and Maven POM with transitive Tink dependency |
| ABI | arm64-v8a and x86_64 |
| Toolchain | compile/target 36; NDK `28.0.13004108`; Runtime min 24 |
| Packaging | ZIP alignment and 16 KiB ELF `PT_LOAD` checks |
| Offline assets | Identical module, public key, and bootstrap in APK/AAB/R8 |
| Physical smoke | HONOR BRP-AN00, API 35, startup/events/restore |

These are development/test builds and one-device longitudinal evidence, not a
production signature or complete OEM/API/lifecycle matrix.

## iOS evidence

| Evidence | Result |
|---|---|
| Swift Package | iOS 15 targets for core, bridge, and Swift runtime |
| Host | `@MainActor PVMHost` with C ABI v3 bindings |
| XCFramework | complete precompiled Swift/Objective-C++/C++ Runtime; device arm64 and simulator arm64/x86_64 |
| Consumer | stable Swift interfaces, Swift 6 complete strict concurrency, and a real binary link probe |
| Artifact scan | headers, private-key suffixes, module suffixes, local paths |
| Demo | Xcode target with signed offline module and basic capabilities |
| Simulator | count/input/async storage and screenshot on iOS 26.2 |

The simulator `.app` uses local ad-hoc signing and is not an archive, IPA,
physical-device lifecycle result, Apple Distribution signature, entitlement
review, privacy questionnaire, or App Store decision.

## HarmonyOS evidence

| Evidence | Result |
|---|---|
| Project | DevEco API 24; compatible API 23 |
| Runtime | `dist/harmony/pvm-runtime-0.5.0.har` |
| Demo | unsigned Offline Sealed emulator HAP |
| ABI | arm64-v8a and x86_64 Node-API/C++17 |
| Assets | platform/profile/hash-bound module, key, bootstrap |
| Device | Pura 70 ADY-AL10, HarmonyOS 6.1 |
| Interaction | count 0→1→2, async storage, input, force-stop restore |

The repository HAP is unsigned. Physical smoke used a separately generated
Huawei debug-signed HAP. It is not commercial/release/AppGallery evidence.

## Planned-phase mapping

| Original phase | Repository delivery | Automated acceptance | External evidence |
|---|---|---|---|
| Months 4–9 | hosts, verification, native renderers, LKG, profiles, mobile SDK/demo baselines | platform and artifact gates | broad labs and release signing |
| Months 10–18 | Host/component IDL and capability contracts | `make verify-contracts` | commercial adapters and sandbox credentials |
| Months 19–27 | remote signer, signed manifest, rollback, rollout, audit | tests, sanitizers, fuzz | production HSM, stores, red team |
| Months 28–36 | historical compatibility and delivery governance | compatibility and release gates | real traffic, SLOs, upgrade drills |

## Automated gates

[`spec/release_gates.json`](../spec/release_gates.json) is the machine-readable
source.

| Gate | Command | Evidence |
|---|---|---|
| Core | `make test` | compile, execute, C ABI, tamper, state, HTTP, rollout |
| Hosts | `make platform-check` | platform-host buildable portions |
| Contracts | `make verify-contracts` | Host IDL and renderer conformance |
| Documentation | `make docs-check` | bilingual pairs, links, visual assets |
| Profiles | `make delivery-matrix` | 12 platform/profile outputs |
| Android | `make android-demo-check` | APK/AAB/AAR/Maven and package security |
| iOS | `make ios-sdk-check ios-demo-check` | XCFramework and simulator app |
| HarmonyOS | `make harmony-sdk-check` | HAR/HAP, ABIs, offline assets |
| KMP | `make kmp-check` | common/JVM/iOS compile and lifecycle |
| SDK release | `make sdk-release-assets` | versioned AAR/Maven, Binary Swift Package/XCFramework, HAR, checksums |
| History | `make compatibility` | 15 historical upgrade cases |
| Native safety | `make sanitizer-check fuzz-check` | sanitizer and parser fuzz smoke |

`make release-check` aggregates SDK-independent gates. Android, Xcode, and
DevEco artifact gates remain separate because each requires its platform SDK.

## Required external evidence

- KMS/HSM key IDs, access policy, rotation drill, and audit export.
- Google Play, Apple, and Huawei decisions for the exact profile and release.
- Broader Android/iOS/HarmonyOS physical-device and lifecycle matrices.
- Billing sandboxes and receipt verification.
- Black-box, rooted/jailbroken, hooking, and partial-source-loss assessments.
- Production TLS/auth/CDN failover, performance percentiles, cold start, memory,
  rollout stop, higher-release business rollback, and recovery drills.

## Anti-rollback acceptance

`pvm_server.release --rollback` sets rollout to zero and stops new upgrades. A
device that already accepted a release keeps its LKG and will not accept a lower
release. Business rollback means:

```text
old business behavior + higher release + new signature
```

Lowering `minimumRelease`, clearing state/LKG to force an old module, replacing
content at an existing hash URL, returning an unsigned manifest, or bypassing
preload validation are acceptance failures.

## Remaining core phases

1. **HarmonyOS production completion:** HUKS, online Module Store, remaining
   capabilities, commercial/AppGallery signing, and broader devices.
2. **KMP/CMP product integration:** Android/iOS actual runtime ports and the
   selected Compose host; Kuikly only if the product adopts it.
3. **Production acceptance and operations:** iOS physical archive/distribution,
   HSM and rotation, release-signed packages, full device/capability matrices,
   SLOs, monitoring, red team, stores, and billing sandboxes.

See [Operations](OPERATIONS.md) and [Security model](SECURITY_MODEL.md).
