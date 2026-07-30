[简体中文](README.zh-CN.md)

# PVM Runtime documentation hub

This directory records design constraints, executable contracts, production
integration boundaries, and acceptance evidence. The repository README is a
product overview; these documents explain why the system is designed this way,
how to integrate it correctly, and what evidence counts as complete.

## Recommended reading order

### First introduction

1. [Repository README](../README.md)
2. [Architecture and data flow](ARCHITECTURE.md)
3. [Functional status](FUNCTIONAL_STATUS.md)

### Writing business modules

1. [DSL and bytecode](DSL_V1.md)
2. [Selective legacy migration](MIGRATION.md)
3. [Migration Studio](MIGRATION_STUDIO.md)
4. [Security model](SECURITY_MODEL.md)
5. [`server/sample/counter.pvm.json`](../server/sample/counter.pvm.json)

### Integrating a mobile app

1. [Platform integration](PLATFORM_INTEGRATION.md)
2. [Delivery status](DELIVERY_STATUS.md)
3. [Renderer conformance](../spec/renderer_conformance.json)
4. [Host IDL](../spec/host_idl.json)

### Release and on-call

1. [Operations](OPERATIONS.md)
2. [Security model](SECURITY_MODEL.md)
3. [Delivery status](DELIVERY_STATUS.md)
4. [Security policy](../SECURITY.md)

## Document map

| Document | Answers |
|---|---|
| [Architecture](ARCHITECTURE.md) | Which component owns each trust decision and data transition? |
| [DSL and bytecode](DSL_V1.md) | What can a module express and how does the VM validate it? |
| [Selective migration](MIGRATION.md) | How are individual classes or existing modules converted safely? |
| [Migration Studio](MIGRATION_STUDIO.md) | How does the desktop workflow scan, review, and verify a selection? |
| [Security model](SECURITY_MODEL.md) | What is protected, from whom, and what is explicitly out of scope? |
| [Platform integration](PLATFORM_INTEGRATION.md) | How do Android, iOS, HarmonyOS, and KMP connect? |
| [Operations](OPERATIONS.md) | How are modules built, signed, rolled out, stopped, and audited? |
| [Functional status](FUNCTIONAL_STATUS.md) | Which code is real and which adapters remain? |
| [Delivery status](DELIVERY_STATUS.md) | Which claims have automated or external evidence? |

## Core terminology

| Term | Meaning |
|---|---|
| DSL | Build-time business description; never interpreted on device |
| PVBC | Verified private bytecode payload |
| PVMP | Signed module container around PVBC |
| Manifest | Signed release selection and immutable module metadata |
| Runtime | Shared C++17 verifier and interpreter |
| Host | Platform lifecycle, renderer, Module Store, and capabilities |
| UI Tree | Neutral whole-tree UI batch emitted by the VM |
| Capability | Versioned, declared call into native host functionality |
| Native Surface | Host-owned native view for maps, players, camera, and similar features |
| LKG | Last known good verified module |
| Delivery Profile | Policy describing how a platform-bound module reaches the device |

## Version relationships

- Runtime 5 reads PVBC v1–v5.
- The compiler emits PVBC v5 by default.
- C ABI v3 is the required mobile binding API.
- Host IDL, renderer conformance, release gates, and state persistence are
  independently versioned contracts.
- Runtime, bytecode, platform package, and business release are related but not
  interchangeable version numbers.

## Current runnable delivery

The repository can build and inspect the C++17/Qt Migration Studio, Android
APK/AAB/AAR/Maven, the complete binary iOS XCFramework and Simulator demo,
HarmonyOS HAR and unsigned emulator HAP, KMP Maven variants, the delivery
matrix, and the desktop module-service loop. `make sdk-release-assets`
assembles the three precompiled consumer SDKs. Physical-device smoke exists for
one Android and one HarmonyOS device; iOS evidence currently uses Simulator.
See [Delivery status](DELIVERY_STATUS.md) before making a production claim.

## Documentation maintenance

- English files use `NAME.md`; Simplified Chinese uses `NAME.zh-CN.md`.
- Every pair links to the other language and changes in one language update the
  peer in the same PR.
- Status claims name the command, artifact, simulator, device, account, or
  external evidence that proves them.
- A compiled interface is not described as an implemented adapter.
- Simulator evidence is not described as physical-device evidence.
- Development signing is not described as production signing.
- `make docs-check` enforces pairing, links, and visual-asset integrity.

See [Contributing](../CONTRIBUTING.md) for the Issue-to-PR workflow.
