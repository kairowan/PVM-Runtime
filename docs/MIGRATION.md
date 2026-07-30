[简体中文](MIGRATION.zh-CN.md)

# Selective legacy-project migration

PVM migration is local, read-only analysis followed by reviewable generation.
It does not rewrite the source project. A migration selection can contain one
class, multiple classes, one module directory, multiple module directories, or
the union of class and module selectors.

For the guided C++17/Qt interface, see
[PVM Migration Studio](MIGRATION_STUDIO.md).

## Supported source

The dependency-free scanner currently recognizes declarations in Kotlin,
Java, Swift, and ArkTS (`.kt`, `.java`, `.swift`, and `.ets`). It records:

- declarations, imports, and referenced local declarations;
- mutable state with safe literal `int`, `bool`, or `string` defaults;
- PVM UI node hints;
- likely Host Capability requirements;
- reflection, concurrency, dynamic loading, custom drawing, and web content
  that require manual review.

The scanner skips build outputs, dependency directories, symlinks, non-UTF-8
files, and individual source files larger than 2 MiB.

## Scan before converting

Run every command from the repository root. Scanning the entire source tree is
allowed because it only produces an inventory:

```bash
PYTHONPATH=server/src python3 -m pvm_server.migrate scan \
  /path/to/legacy-project \
  --output build/migration/inventory.json
```

Select one class by simple name, qualified name, or an unambiguous
`relative/path.ext:ClassName` selector:

```bash
PYTHONPATH=server/src python3 -m pvm_server.migrate scan \
  /path/to/legacy-project \
  --class com.example.checkout.CheckoutViewModel
```

Repeat `--class` to combine multiple classes:

```bash
PYTHONPATH=server/src python3 -m pvm_server.migrate scan \
  /path/to/legacy-project \
  --class CheckoutViewModel \
  --class CheckoutRepository \
  --class app/profile/ProfileView.swift:ProfileView
```

Select one or more module directories. Android-style `:feature:checkout`
notation is accepted as an alias for `feature/checkout`:

```bash
PYTHONPATH=server/src python3 -m pvm_server.migrate scan \
  /path/to/legacy-project \
  --module :feature:checkout \
  --module ios/Features/Profile
```

Class and module selectors form a union. Add `--include-dependencies` to include
unambiguously referenced declarations found inside the same source tree.
Without it, those declarations remain in `unselectedLocalDependencies` for
explicit review.

## Generate the migration scaffold

`convert` requires at least one class or module selector. This prevents an
accidental whole-project conversion:

```bash
PYTHONPATH=server/src python3 -m pvm_server.migrate convert \
  /path/to/legacy-project \
  --class CheckoutViewModel \
  --class CheckoutRepository \
  --include-dependencies \
  --application-id com.company.existingapp \
  --platform android \
  --profile offline_sealed \
  --module-id checkout.flow \
  --release 1 \
  --output build/migration/checkout
```

Run conversion separately for Android, iOS, and HarmonyOS because a PVM module
is bound to one application ID, platform, delivery profile, and release.

The output directory contains:

```text
build/migration/checkout/
├── module.pvm.json          compiler-validated DSL scaffold
├── capabilities.json       Capability decisions and adapter/test evidence
├── migration-approvals.json review decisions for every scanner finding
├── migration-cases.json     behavior cases anchored to legacy tests
├── migration-report.json   machine-readable inventory and review findings
└── migration-report.md     bilingual human review checklist
```

The output must be outside the legacy source root. The tool refuses to
overwrite an existing output unless `--force` is supplied, and it never
replaces unknown files in that directory.

## What is converted automatically

Safe mutable literal state is copied into the DSL state schema. Non-empty
string defaults are redacted, and names that look like credentials, tokens,
passwords, or private keys are not copied. Duplicate state names are scoped by
their source declaration.

The generated page makes converted state visible and is compiled by the real
PVM compiler before it is written. UI hints are deliberately not treated as a
completed layout conversion: native framework builders, modifiers,
constraints, and custom views need review to preserve behavior.

Capabilities are suggestions only. They are not automatically granted to the
module. Review `capabilities.json`, approve the minimum set, then implement
each approved capability with the existing application's services.

## Verification gates

Structural verification can run immediately after conversion:

```bash
PYTHONPATH=server/src python3 -m pvm_server.migrate verify \
  build/migration/checkout \
  --source /path/to/legacy-project
```

It rescans the exact original selection and compares each selected source
file's SHA-256. It also requires canonical DSL JSON, compiles it with the real
PVM compiler, and lints it against the versioned Host IDL. A successful
structural check writes `verification.json` with
`"result": "structurally_valid"`; this is not production approval.

Before strict verification, resolve every item in
`migration-approvals.json`. Valid final statuses are `resolved` and `accepted`,
and each item requires a non-empty note:

```json
{
  "id": "generated-stable-id",
  "status": "resolved",
  "note": "Included CheckoutRepository and matched its existing unit tests."
}
```

Every entry in `capabilities.json` must be decided:

- `approved` requires a non-empty `adapter` and at least one test identifier;
- `excluded` requires a non-empty explanation;
- `pending` blocks strict verification.

The capabilities declared in `module.pvm.json` must exactly equal the approved
Capability decisions. This prevents a scanner hint from silently granting a
permission or an edited DSL from adding an unreviewed host call.

Add behavior cases to `migration-cases.json`:

```json
{
  "schemaVersion": 1,
  "cases": [
    {
      "name": "initial checkout state",
      "legacyEvidence": "CheckoutViewModelTest#initialState",
      "steps": [
        {
          "expectedOutput": [
            "text=\"CheckoutViewModel\"",
            "text=\"total: 0\""
          ],
          "forbiddenOutput": ["error:"]
        }
      ]
    }
  ]
}
```

`legacyEvidence` must point to a test or captured assertion from the old
implementation. Each case has an isolated state file; later steps may add
`"tapIndex": 0`, and state persists between steps in the same case.

Build the desktop verifier and create development keys, then run the strict
gate:

```bash
make bootstrap build

PYTHONPATH=server/src python3 -m pvm_server.migrate verify \
  build/migration/checkout \
  --source /path/to/legacy-project \
  --strict \
  --runtime build/client/pvm_cli \
  --private-key server/var/keys/dev-private.pem \
  --public-key server/var/keys/dev-public.pem
```

Strict verification signs the generated module with the supplied development
key, loads it through the C++17 VM, executes every behavior step, and checks
required and forbidden output. It returns a non-zero exit code for source
drift, invalid DSL, pending review, inconsistent Capability decisions, missing
legacy evidence, runtime failure, or output mismatch. Only a report with
`"result": "verified"` passes this gate.

The behavior runner does not execute an arbitrary legacy build command. The
old project's referenced tests must still run in the same CI workflow. Native
layout, lifecycle, accessibility, screenshots, and device-only capabilities
remain platform integration tests rather than console behavior cases.

## Required review

Before routing production traffic to a migrated page:

1. Rebuild the intended UI hierarchy from the recorded UI hints.
2. Confirm state types, persistence IDs, redacted defaults, and lifecycle.
3. Resolve every unselected or ambiguous local dependency and manual-review
   finding.
4. Approve only the required capabilities and declare their permissions.
5. Compare the legacy and PVM implementations with the same behavior tests.
6. Compile and sign a separate module for every target platform/profile.
7. Require `verification.json` to contain `"result": "verified"` in CI.

Run the selector and generation regression check with:

```bash
make migration-check
```
