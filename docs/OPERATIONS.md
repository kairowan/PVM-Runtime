[简体中文](OPERATIONS.zh-CN.md)

# Release and operations

All commands run from the repository root.

## Environment tiers

| Environment | Signing | Module service | Purpose |
|---|---|---|---|
| Local | ignored development key | localhost HTTP | development loop |
| CI/Staging | isolated test signer | test HTTPS repository | integration and rollout drills |
| Production | KMS/HSM signer | authenticated HTTPS/CDN/private repository | release |

Never copy local development private keys into CI or production.

## Local loop

```bash
make demo
```

For separate processes:

```bash
make bootstrap build
make publish
PVM_ACTIVATION_TOKEN='replace-me' make serve
```

The default service listens on `127.0.0.1:8080`. Online and enterprise
manifest/module requests require a bearer token.

## Pre-release gates

```bash
make release-check
```

| Command | Scope |
|---|---|
| `make test` | compile, signatures, tamper, paths, migration, HTTP, rollout, LKG |
| `make platform-check` | platform host build checks |
| `make verify-contracts` | Host IDL, DSL lint, renderer conformance |
| `make docs-check` | bilingual Markdown pairs, links, visual assets |
| `make delivery-matrix` | Android/iOS/HarmonyOS × four profiles |
| `make compatibility` | five domains × historical PVBC |
| `make sanitizer-check fuzz-check` | native memory safety and parser smoke |

Run platform artifact gates in their SDK environments:

```bash
make android-demo-check
make ios-sdk-check ios-demo-check
make harmony-sdk-check
make kmp-check
```

## Publish precompiled SDKs

On the release Mac with Android SDK, Xcode, and DevEco installed:

```bash
make sdk-release-assets
```

The command builds and verifies AAR/Maven, the complete binary iOS
XCFramework/local Binary Swift Package, and HAR, then writes versioned files
and `SHA256SUMS` under `dist/release/`. After reviewing the inventory:

```bash
git tag -a v0.5.0 -m "PVM Runtime 0.5.0"
git push origin v0.5.0
gh release create v0.5.0 dist/release/* --verify-tag --generate-notes
```

Publishing the GitHub Release triggers `Publish Android SDK`, which publishes
`com.protectedvm:pvm-runtime:0.5.0` to GitHub Packages. The separate
`Attach Production Android Assets` workflow only appends explicitly signed
APK/AAB files to that existing release.

All repository Android targets and the platform host gate set
`GRADLE_USER_HOME` to `build/android-gradle-home`. They do not clean or write
another desktop project's shared Gradle cache.

Android production artifacts require target-app signing secrets:

```bash
PVM_ANDROID_KEYSTORE=/secure/path/release.jks \
PVM_ANDROID_STORE_PASSWORD='...' \
PVM_ANDROID_KEY_ALIAS='...' \
PVM_ANDROID_KEY_PASSWORD='...' \
make android-production-packages
```

iOS distribution evidence uses:

```bash
PVM_IOS_DEVELOPMENT_TEAM=TEAMID \
PVM_IOS_SIGNING_IDENTITY='Apple Distribution' \
PVM_IOS_PROVISIONING_PROFILE_SPECIFIER='Profile Name' \
make ios-device-archive
```

HarmonyOS production validation requires an explicitly selected Huawei-signed
HAP; signing credentials remain in DevEco or the organization signing service.

## KMP artifacts

```bash
make kmp-check
make kmp-packages
```

Outputs are written to `dist/kmp/maven`. KMP uses the repository-local
`build/gradle-kmp-home` cache and never cleans another desktop project's Gradle
cache.

## Compile and publish

### Local private key

```bash
PYTHONPATH=server/src python3 -m pvm_server.publish \
  server/sample/counter.pvm.json \
  --private-key server/var/keys/dev-private.pem \
  --repository server/var/repository
```

### Remote signer

```bash
PYTHONPATH=server/src python3 -m pvm_server.publish \
  server/sample/counter.pvm.json \
  --signer-command '/opt/company/pvm-signer --environment production' \
  --repository /srv/pvm/repository
```

The signer receives the exact payload on stdin and writes only a 64-byte
Ed25519 signature to stdout. Diagnostics go to stderr and failure uses a
non-zero exit code. Production signer policy should bind environment, key ID,
actor, artifact hash, and approval.

Publication:

1. lints DSL, IDL, profile, and budget contracts;
2. compiles deterministic PVBC;
3. signs and verifies the module;
4. writes the immutable hash-addressed module;
5. creates and signs a new manifest payload;
6. atomically replaces control state and resets rollout to 100%.

## Repository layout

```text
repository/
├── modules/
│   └── <sha256>.pvm
└── apps/<application>/<channel>/<platform>/<profile>/
    ├── access.json
    └── manifest.json
```

`manifest.json` is a server-side control object:

```json
{
  "current": {"payload": "...", "signature": "..."},
  "previous": {"payload": "...", "signature": "..."},
  "rollout_percentage": 100
}
```

Only signed envelopes are trusted by the device. The rollout percentage is an
operational selector, not signed release authority.

## Rollout

Start with a stable cohort:

```bash
PYTHONPATH=server/src python3 -m pvm_server.release \
  path/to/manifest.json --percentage 10
```

Observe activation, verification, preload, crash-free sessions, capability
errors, state migration, and business metrics before expanding:

```bash
PYTHONPATH=server/src python3 -m pvm_server.release \
  path/to/manifest.json --percentage 25
PYTHONPATH=server/src python3 -m pvm_server.release \
  path/to/manifest.json --percentage 100
```

Installation IDs map to stable buckets, so a device does not oscillate between
current and previous during a rollout.

## Emergency stop and business rollback

```bash
PYTHONPATH=server/src python3 -m pvm_server.release \
  path/to/manifest.json --rollback
```

This sets rollout to zero and stops additional upgrades. It does not lower the
release floor on devices that already accepted the release. To restore old
behavior there, publish the old behavior as a newly signed, higher release.

Never lower `minimumRelease`, overwrite an existing hash URL, return an unsigned
manifest, clear LKG to force downgrade, or bypass preload validation.

## Manifest and module service

Development:

```bash
PVM_ACTIVATION_TOKEN='replace-me' \
PYTHONPATH=server/src \
python3 -m pvm_server.serve \
  --repository server/var/repository \
  --audit-log server/var/audit.jsonl
```

Production should additionally configure TLS 1.2+, token-file rotation, read
timeouts, request-size limits, reverse-proxy/CDN policy, liveness/readiness, and
an organization audit sink.

The reference service provides ETag, private cache headers for manifests,
immutable long-lived cache headers for modules, request IDs, no-sniff and frame
protection, same-origin module URLs, activation authorization, and profile
access policy.

## Audit

JSONL records manifest selection, release, rollout bucket, module fetches,
request ID, status, actor where available, and timestamp. Production should
correlate:

- manifest 200/304/401/409/500;
- signature, binding, rollback, hash, and preload failures;
- rollout changes and signer approvals;
- cache activation and LKG fallback;
- platform/app/version/device cohort without storing unnecessary personal data.

## Incident handling

### Manifest service unavailable

Keep the local LKG, apply bounded retry with jitter, preserve built-in fallback
UI for profiles that require it, and never return an unsigned temporary
manifest.

### New module verification fails

Set rollout to zero, preserve the bad module and signed envelope for analysis,
keep current LKG, and publish a corrected higher release.

### Signing key suspected compromised

Revoke signer access, freeze manifest control writes while preserving immutable
reads, rotate trust through the platform release process, inventory every
artifact signed by the key, and do not “repair” history by deleting audit data.

### State migration fails

Stop rollout, retain the previous LKG and snapshot, reproduce with the exact
module pair, and publish a higher release with corrected persistence IDs or an
explicit product migration.

## Release record

Archive source revision, compiler/runtime/PVBC version, target/profile,
capability IDL hash, module SHA-256, manifest payload hash, signer key ID,
artifact hashes, automated gates, device evidence, rollout approvals, store
submission IDs, known limitations, and rollback owner.
