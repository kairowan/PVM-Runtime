[简体中文](DSL_V1.zh-CN.md)

# DSL and bytecode v1/v2/v3/v4/v5

PVM currently uses JSON as a deterministic syntax carrier. JSON is build input
only; clients do not interpret JSON, and production modules contain compact
private PVBC tables and instructions.

See [`server/sample/counter.pvm.json`](../server/sample/counter.pvm.json).

## Top-level structure

```json
{
  "module": {},
  "delivery": {},
  "state": {},
  "handlers": {},
  "pages": {}
}
```

| Section | Purpose |
|---|---|
| `module` | app/tenant/channel/release, capabilities, domains, storage, budgets |
| `delivery` | target platform and delivery profile |
| `state` | static type, initial value, persistence identity |
| `handlers` | stack instructions and effects |
| `pages` | neutral UI tree, templated properties, events |

## Module declaration

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

Key constraints:

- `application_id`, `channel`, `id`, and `tenant` are safe path identifiers.
- `release` is positive and strictly greater than the repository release when
  publishing.
- `minimum_runtime` is compatible with the selected PVBC and current Runtime.
- Capabilities are unique, declared, and present in
  [`spec/host_idl.json`](../spec/host_idl.json).
- Network and storage effects require declared domains and scopes.
- Runtime applies hard ceilings to all compiled budgets.

## Delivery profile

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

Platforms are `android`, `ios`, `harmonyos`, and the reference `desktop`.
Profiles are `offline_sealed`, `online_provisioned`, `store_on_demand`, and
`enterprise_managed`.

The compiler rejects contradictory declarations:

- Offline must contain all startup dependencies.
- Online Provisioned requires host fallback UI.
- iOS Store On-Demand cannot declare native dynamic download.
- Android Store On-Demand cannot declare external `.dex`, `.jar`, or `.so`.

For iOS, `offline_sealed` is the default recommendation. Online signed-bytecode
delivery must be reviewed against the exact product and
[Apple Guideline 2.5.2](https://developer.apple.com/app-store/review/guidelines/).

## State

| DSL type | Runtime type | Persistent encoding |
|---|---|---|
| `int` | signed 64-bit integer | little-endian 64-bit |
| `bool` | Boolean | 0 or 1 |
| `string` | UTF-8 string | length + bytes |

PVBC v4 requires a stable `persistence_id`:

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

### State migration

Keep the old persistence ID when renaming a field:

```json
{
  "total": {
    "type": "int",
    "persistence_id": "count",
    "initial": 0
  }
}
```

- Matching ID and type restores the old value.
- A new ID uses `initial`.
- Removed IDs are ignored.
- A type change for an existing ID rejects restore.
- Empty, unsafe, or duplicate persistence IDs fail compilation.
- A non-empty snapshot with no matching field is rejected.

`persistence_id` is a persistent contract and must not be mechanically renamed
with a source variable.

## UI tree

```json
{
  "pages": {
    "main": {
      "type": "column",
      "id": "counter_root",
      "props": {"accessibility_label": "Counter"},
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

### Nodes

`text`, `image`, `row`, `column`, `stack`, `scroll`, `list`, `button`, `input`,
`switch`, and `native_surface`.

### Properties

`text`, `source`, `accessibility_label`, `enabled`, `value`, and `surface_type`.
`{stateName}` inserts read-only state. The compiler stores constant and state
slots, not template source.

### Events

`tap`, `change`, `submit`, and `appear`.

Each source `id` becomes a stable FNV-1a 32-bit numeric node ID. Source IDs are
not stored and hash collisions fail compilation.

PVBC v5 lets `change` and `submit` carry a host-control value:

```json
{
  "set_name": [
    {"op": "event.value"},
    {"op": "state.set", "name": "name"},
    {"op": "render", "page": "main"}
  ]
}
```

Android View, UIKit/SwiftUI, and ArkUI forward Input text or Switch
`"true"`/`"false"`. `event.value` fails for events without a value, and values
are constrained by `max_state_bytes`. `appear` means absent→present: a node
remaining in consecutive whole-tree replacements does not emit again.

## Handlers and instructions

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

| Instruction | Stack effect |
|---|---|
| `const` | push `int`, `bool`, or `string` |
| `event.value` | push current event string; PVBC v5 |
| `state.get` | push state value |
| `state.set` | pop value matching the state type |
| `int.add` | pop two ints, check overflow, push result |
| `equal` | pop two same-type values, push bool |
| `jump` | jump within the handler |
| `jump_if_false` | pop bool and branch when false |
| `effect` | pop arguments, call sync capability, push string |
| `effect.async` | pop arguments, save continuation, later push string |
| `pop` | discard stack top |
| `render` | emit a page |
| `halt` | terminate; compiler appends it when omitted |

The compiler validates every reachable control-flow state: no underflow, correct
types, equal stack shapes at joins, in-handler jumps, empty stack at halt, and
declared capabilities with IDL-matching arguments. Runtime independently repeats
validation when loading.

## Asynchronous effects

`effect.async` is available from PVBC v2. The VM stores a continuation and
64-bit task ID; the host completes it through `pvm_runtime_complete_effect`.
Lifecycle shutdown calls `pvm_runtime_cancel_all_tasks`.

Results are currently strings and are constrained by result/state size and
`max_tasks`. Cancellation removes continuations, and all platform hosts discard
late callbacks after cancel or close.

## Package format

```text
PVMP
  package format = 1
  signature algorithm = Ed25519
  payload length
  signature length = 64
  PVBC payload
  signature
```

The signature covers the complete payload, including bindings, budgets,
capability/domain/storage tables, constants, state, handlers, UI nodes, and the
entry point.

## Version evolution

| PVBC | Added capability | Runtime 5 |
|---|---|---|
| v1 | sync effects, UI, state, budgets | reads |
| v2 | `effect.async`, `max_tasks` | reads |
| v3 | minimum capability versions | reads |
| v4 | stable persistence IDs and migration snapshots | reads |
| v5 | `event.value` input/switch values | default output |

The historical matrix covers five domains × v1/v2/v3. v4/v5 are covered by
main end-to-end, migration, input-event, platform-delivery, and fuzz gates.

## Build commands

```bash
PYTHONPATH=server/src python3 -m pvm_server.tooling lint \
  server/sample/counter.pvm.json

PYTHONPATH=server/src python3 -m pvm_server.compiler \
  server/sample/counter.pvm.json \
  --private-key server/var/keys/dev-private.pem \
  --output build/counter.pvm

PYTHONPATH=server/src python3 -m pvm_server.compiler \
  path/to/module.json --format-version 3 \
  --private-key server/var/keys/dev-private.pem \
  --output build/module-v3.pvm
```

Production builds use a remote signer instead of a local private key.

## Current language boundary

The DSL is the smallest language required to lock runtime, protected delivery,
and platform-host semantics. Records, collections, generics, pattern matching,
structured exceptions, timeout/retry, and module dependencies are intentionally
not implemented. They should evolve only with demonstrated product demand and
an explicit compatibility strategy.
