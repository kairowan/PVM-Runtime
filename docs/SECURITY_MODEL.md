[简体中文](SECURITY_MODEL.zh-CN.md)

# Security model

PVM Runtime makes business modules verifiable, constrained, and recoverable
through build, delivery, cache, and execution. It raises the cost of ordinary
reverse engineering, content replacement, and incorrect release. It is not DRM
and does not promise confidentiality on a fully compromised device.

## Protection goals

- prevent unauthorized or modified modules from executing;
- prevent cross-application/channel/platform/profile reuse;
- prevent accepted devices from loading a lower release;
- constrain bytecode, state, stack, UI, tasks, domains, and capabilities;
- preserve a verified LKG when refresh fails;
- keep privileged native capability behind host policy;
- reduce source-level names and structure in production packages;
- maintain auditable publication and rollout.

## Explicit non-goals

- absolute resistance to a rooted, jailbroken, debugged, or instrumented device;
- protection after source, build chain, and all signing keys are simultaneously
  compromised;
- replacing trusted-server authorization, pricing, entitlement, or anti-fraud;
- allowing remote modules to add permissions or deliver native executable code;
- claiming store compliance solely because modules are signed or interpreted.

## Attacker model

The design considers an attacker who can inspect packages and caches, intercept
or replay network traffic, alter manifests/modules/files, call public APIs with
malformed input, submit malicious DSL to a compromised build account, force
process death, replay old signed releases, and fuzz the package parser.

A fully compromised kernel, platform trust store, build administrator, or HSM
administrator is outside the single-control boundary and requires organization
controls, monitoring, and incident response.

## Trust boundaries

| Boundary | Trusted material | Untrusted input |
|---|---|---|
| Build | reviewed compiler, IDL, profile policy, signer authorization | DSL and dependencies |
| Signer | isolated private key and approval policy | payload bytes and caller |
| Delivery | immutable hash storage and access policy | network clients and rollout input |
| Device store | embedded public key, app identity, release floor | manifest, module, cache files |
| VM | verified module metadata and hard limits | all package and bytecode bytes |
| Host capability | adapter implementation and platform permission state | module operation and arguments |

No delivery response becomes trusted merely because it came over TLS. Signature,
binding, release, hash, and preload checks are still mandatory.

## Signed objects

### Module

Ed25519 covers the entire PVBC payload, including format, minimum Runtime,
release, key version, application/tenant/channel/platform/profile binding,
budgets, capabilities, domains, storage scopes, constants, state, handlers, UI
nodes, and entry point.

PVMP length limits and parser bounds are checked before allocation or table
access. The signature is verified before business tables are interpreted.

### Manifest

The signed envelope authorizes a specific application/channel/platform/profile,
release, immutable module URL, SHA-256, size, and required metadata. Rollout
percentage is a server-side selector; it cannot grant authority for an unsigned
or different release.

The client requires same-origin content-addressed URLs and verifies both the
manifest and module.

## Anti-rollback

Three values cooperate:

1. the target app's installation `minimumRelease`;
2. the highest accepted/current LKG release;
3. the signed manifest and module release.

A candidate lower than the floor is rejected. Operational rollout rollback only
stops additional upgrades. Restoring old business behavior requires a higher,
newly signed release.

State and cache deletion must not be used as a downgrade mechanism. The target
app should protect its release floor with platform storage and organization
policy.

## Bytecode security boundary

Compiler and Runtime independently enforce:

- valid tables, indexes, lengths, UTF-8, and numeric ranges;
- in-handler jumps and reachable control flow;
- stack underflow, type correctness, and equal join shapes;
- integer overflow checks;
- empty stack at halt;
- instruction, stack, state, UI-node, package-size, result-size, and task budgets;
- declared capabilities, versions, domains, scopes, and IDL argument counts;
- lifecycle and task-continuation validity.

The watchdog limits instructions per event. Native frames and high-frequency
streams never traverse the VM.

## Update and cache security

Candidate files use a temporary path, size/hash check, signature verification,
VM preload, then atomic rename and current-state update. Failure leaves the LKG
unchanged. Current-state records are strictly bound and retain at most two
verified hashes.

Platform file encryption can reduce casual extraction but is defense in depth.
It must not replace signatures or allow unverifiable recovery.

## Key management requirements

- Development keys stay ignored and never enter release packages.
- Production signing uses KMS/HSM or an isolated signing service.
- Signer authorization records environment, actor, approval, key ID, and
  payload hash.
- Public-key rotation is shipped through a trusted platform-app release and may
  use a bounded dual-trust window.
- Key compromise freezes new publication, preserves immutable reads and audit,
  inventories signed artifacts, rotates trust, and publishes corrected higher
  releases.
- Keys, tokens, profiles, and signing files are never attached to Issues or PRs.

## Failure policy

| Failure | Required behavior |
|---|---|
| manifest unavailable | use verified LKG or profile fallback; bounded retry |
| manifest signature/binding invalid | reject and alert; do not fetch candidate |
| module hash/signature invalid | delete temporary file and retain LKG |
| preload/bytecode/capability invalid | reject activation and retain LKG |
| current-state corrupt | do not treat it as LKG; use verified history/bundled fallback |
| state migration incompatible | retain snapshot/LKG and stop rollout |
| async result after cancel/close | discard without entering VM |

Fail-open behavior is prohibited for signature, binding, rollback, hash, native
code policy, and capability declaration.

## Production acceptance checklist

- isolated signer/HSM, least privilege, approval, rotation, and audit;
- release-signed APK/AAB, archive/IPA, and HAP from target accounts;
- physical-device lifecycle, protected storage, background, process death, and
  restore;
- network interception, replay, tamper, cache corruption, and service outage;
- capability permission denial, consent, argument validation, and vendor error;
- sustained fuzz/sanitizer runs and independent review;
- rollout stop and higher-release business rollback drill;
- store policy and payment-sandbox evidence;
- privacy, telemetry retention, alerting, incident ownership, and performance
  SLOs.

Report vulnerabilities through [Security policy](../SECURITY.md), not a public
Issue.
