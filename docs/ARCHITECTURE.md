[简体中文](ARCHITECTURE.zh-CN.md)

# Architecture and data flow

PVM Runtime evolves business expression, protected delivery, and platform
capabilities independently. DSL/bytecode/VM semantics stay shared; a Delivery
Profile only changes how a module reaches a device; UI and privileged features
remain native-host responsibilities.

![PVM Runtime system architecture](assets/system-architecture.svg)

## Design principles

1. **Verify before execute.** A valid signature is only the first gate;
   bytecode is still fully validated as untrusted input.
2. **Declarative business logic is not remote native code.** Modules cannot
   carry DEX, SO, Frameworks, or arbitrary platform calls.
3. **Platform capability remains in the host.** Payments, camera, maps, media
   frames, and scheduling do not enter the VM.
4. **Delivery policy is independent from business source.** Four profiles use
   the same DSL and runtime semantics.
5. **Failure preserves the LKG.** Refresh cannot overwrite a verified module,
   and an operational rollback cannot weaken anti-rollback.
6. **Compatibility is explicitly versioned.** PVBC, Runtime, Host IDL,
   capabilities, and persisted state all have versions or stable identities.

## Three trust planes

### Build Plane

| Component | Responsibility |
|---|---|
| DSL source | Module binding, state, pages, handlers, effects, budgets, delivery profile |
| `compiler.py` | Semantic/type/control-flow/profile checks and deterministic PVBC |
| `tooling.py` | Capability, operation, and argument checks against Host IDL |
| signer | Ed25519 signing of module and manifest payloads |
| `delivery_build.py` | Three platforms × four profiles from one DSL |

DSL exists only at the build boundary and is not stored in `.pvm`. Production
modules omit source state names, handler names, source node IDs, comments,
source paths, and source maps.

### Delivery Plane

| Component | Responsibility |
|---|---|
| `publish.py` | Atomic content-addressed modules, policy, history, signed manifest |
| immutable repository | SHA-256 filenames prevent mutable URL replacement |
| `serve.py` | Activation auth, ETag, profile access, stable rollout, audit |
| `release.py` | Rollout and emergency stop without changing signed release data |

Repository keys are:

```text
application_id / channel / platform / profile
```

Application, channel, platform, profile, and release are present in both the
manifest and signed bytecode to prevent cross-application, cross-channel,
cross-platform, or cross-profile loading.

### Device Plane

| Component | Responsibility |
|---|---|
| Module Store | Manifest verification, binding, release floor, download, hash, preload, atomic cache |
| C++17 Runtime | Module verification, bytecode validation, interpretation, snapshots, watchdog |
| UIHost | Native rendering of the neutral UI tree and event return |
| Capability Host | Version, permission, thread, argument, and consent checks before native SDK calls |

Android, iOS, and HarmonyOS share the same runtime and C ABI. C ABI v3 binds
application/channel/platform/profile and release floor at creation. The Module
Store also requires the VM-reported release to equal the signed manifest
release.

## DSL-to-UI flow

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
    Compiler->>Signer: canonical manifest payload
    Signer-->>Repo: signed manifest envelope
    Store->>Repo: GET manifest + installation ID
    Repo-->>Store: selected signed envelope
    Store->>Store: verify signature/binding/release
    Store->>Repo: GET /v1/modules/&lt;sha256&gt;.pvm
    Repo-->>Store: immutable module
    Store->>VM: preload validation
    VM-->>Store: metadata + release
    Store->>Store: atomic LKG switch
    Store->>VM: start/restore
    VM->>Host: replace UI tree
    Host->>VM: node event
    VM->>Host: typed capability effect
```

## Module format

### PVMP container

```text
magic "PVMP"
package version
signature algorithm
payload length
signature length
PVBC payload
Ed25519 signature
```

The signature is verified before PVBC business tables are parsed. A package has
a hard 16 MiB limit.

### PVBC payload

PVBC contains:

- format and minimum Runtime;
- release, key version, and application/tenant/channel/platform/profile binding;
- state schema and v4 stable persistence IDs;
- resource budgets;
- capabilities and minimum versions, network domains, storage scope;
- constant pool, initial state, handlers, UI nodes, and entry point.

Runtime 5 reads v1–v5 and the compiler emits v5 by default. Historical formats
without capability versions are interpreted as capability version 1.

## Manifest and control data

The signed payload contains only release data that operations must not modify.
Repository `manifest.json` additionally stores the current envelope, previous
envelope, and rollout percentage. The service selects current or previous using
a stable installation ID and returns only that signed envelope. The client does
not trust the selection, but can verify that the selected release was authorized
by the release key.

## Loading and atomic updates

```text
signed manifest
  → signature
  → application/channel/platform/profile/release binding
  → same-origin content-addressed URL
  → temporary download
  → size + SHA-256
  → module signature
  → runtime/bytecode/capability preload
  → atomic rename
  → atomic current state
  → retain at most two verified versions
```

Any failure removes the temporary file and keeps the current LKG. Android, iOS,
and HarmonyOS use a strict v1 current-state record: all bindings, positive
release, current hash, non-empty unique history of at most two entries, and
history-first-equals-current are validated before it can become an LKG.

## State lifecycle

PVBC v4 assigns each field an irreversible 64-bit ID derived from application,
module, and `persistence_id`:

- rename a field while keeping `persistence_id` to restore the old value;
- new fields use their initial value;
- removed fields are ignored;
- a type change for the same ID is rejected;
- a non-empty snapshot must match at least one current field.

PVBC v1–v3 retains strict schema-equality restoration.

## Runtime lifecycle

```text
created → optional restore → start exactly once → dispatch/complete/snapshot
                                             └── cancel pending work → destroy
```

- Dispatch and effect completion fail before start.
- Restore is accepted only before start; repeated start is rejected.
- Cancel clears VM continuations. Platform hosts increment task generations or
  release callback ownership so late native results cannot revive a cancelled
  or destroyed VM.
- Host close is idempotent and terminal.

## UI and capability boundary

The VM emits a complete neutral UI tree with node type, stable numeric ID,
properties, events, and children. The host:

- creates and updates native controls on the platform UI thread;
- returns click, input, submit, and appear events;
- permits budget-limited v5 string values for change/submit;
- emits `appear` only on absent→present transitions;
- uses Native Surface for maps, players, and camera previews;
- never routes video frames, camera frames, or gesture streams through the VM.

The Capability Registry applies module metadata before calls are enabled.
Undeclared, unavailable, or underspecified capability versions fail at startup
or at the call boundary.

## Directory ownership

```text
server/src/pvm_server/       compiler, manifest, publication, service, rollout
client/include/pvm/          public C++ and C ABI
client/src/                  verifier, interpreter, state migration, C ABI
client/platform/android/     Kotlin/JNI/View/Module Store
client/platform/ios/         Objective-C++/Swift/Renderer/Module Store
client/platform/harmony/     DevEco/HAR/HAP/Node-API/ArkTS/ArkUI
spec/                        Host IDL, renderer, release gates
generated/                   generated Kotlin/Swift/ArkTS/C++ interfaces
```

## Delivery profiles

![PVM Runtime delivery profiles](assets/delivery-profiles.svg)

Profiles change module origin and packaging constraints, not business semantics.
Android `Offline Sealed` can be embedded in an APK for direct distribution or
an AAB for Google Play. See [Operations](OPERATIONS.md).

## Intentional boundaries

The current runtime uses small complete modules and whole-tree replacement.
Incremental diff should be added only after real page size and frame budgets
show that it is necessary.

Product environments still need platform secure storage, commercial capability
adapters, iOS physical-device/archive/store evidence, HarmonyOS HUKS and
commercial signing, broader device labs, KMP platform actuals and selected
Compose hosts, production KMS/HSM, store review, payment sandboxes, red-team
work, and performance SLOs. See [Security model](SECURITY_MODEL.md) and
[Delivery status](DELIVERY_STATUS.md).
