[简体中文](MIGRATION.zh-CN.md)

# Selective legacy-project migration

PVM migration is local, read-only analysis followed by reviewable generation.
It does not rewrite the source project. A migration selection can contain one
class, multiple classes, one module directory, multiple module directories, or
the union of class and module selectors.

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
├── capabilities.json       unapproved Host Capability suggestions
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

## Required review

Before routing production traffic to a migrated page:

1. Rebuild the intended UI hierarchy from the recorded UI hints.
2. Confirm state types, persistence IDs, redacted defaults, and lifecycle.
3. Resolve every unselected or ambiguous local dependency and manual-review
   finding.
4. Approve only the required capabilities and declare their permissions.
5. Compare the legacy and PVM implementations with the same behavior tests.
6. Compile and sign a separate module for every target platform/profile.

Run the selector and generation regression check with:

```bash
make migration-check
```
