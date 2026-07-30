[简体中文](MIGRATION_STUDIO.zh-CN.md)

# PVM Migration Studio

PVM Migration Studio is a C++17/Qt desktop frontend for selective migration.
It does not contain a second migration engine: Scan, Convert, and Verify invoke
the same scanner, converter, DSL compiler, Host IDL checks, signer, and C++17 VM
used by the command line and CI.

![PVM Migration Studio running a verified conversion](assets/migration-studio.png)

## Workflow

1. Choose the legacy source directory and a repository-local output directory.
2. Add one or more class or module selectors. The application never performs an
   implicit whole-project conversion.
3. Run **Scan** and inspect the selected declarations, dependencies, risk hints,
   and suggested capabilities.
4. Run **Convert** to generate the DSL scaffold and review files.
5. Use the **Review** tab to edit approvals, capabilities, behavior cases, and
   the generated DSL. JSON files are validated and saved atomically.
6. Run **Structural Verify** while filling review decisions.
7. Run **Strict Verify** with the target binding, runtime, and signing keys
   before accepting the migration.

The progress bar consumes JSON Lines events emitted by the migration backend,
so it represents real stages rather than a timer. The current operation can be
cancelled, and the bounded, color-coded log can be copied or exported.

```mermaid
flowchart LR
  UI["Migration Studio<br/>selectors, review, logs"] --> Engine["Existing migration engine"]
  Engine --> Source["Source snapshot<br/>risk and dependency report"]
  Engine --> Review["Approvals, capabilities<br/>and behavior cases"]
  Engine --> DSL["Generated PVM DSL"]
  DSL --> Compiler["DSL compiler + Host IDL"]
  Compiler --> VM["Signed module + C++17 VM verification"]
  Review --> VM
```

## Build and run

From the repository root:

```bash
make migration-studio-package
make migration-studio-run
```

All downloads, source, build caches, and outputs remain under this repository:

| Path | Purpose |
|---|---|
| `tools/migration-studio/` | C++17/Qt application source |
| `third_party/qt/6.12.0/` | Repository-local pinned Qt SDK |
| `build/migration-studio-tools/` | Repository-local `aqtinstall` and archives |
| `build/migration-studio/` | CMake build tree |
| `dist/desktop/PVMMigrationStudio.app` | Relocatable macOS development package |
| `build/migration-studio-output/` | Default migration output |

Only the required Qt Base archive is installed. The macOS application is
dynamically linked to bundled Qt frameworks and includes the corresponding Qt
license and notice files.

## Packaged runtime

The macOS package contains the migration Python backend, JSON specifications,
the C++17 `pvm_cli`, and its Qt runtime. It never packages development private
keys. Python 3.9+ and OpenSSL are currently expected on the host for conversion,
signing, and strict verification.

Backend processes receive argument vectors through `QProcess`; no source path
is interpolated into a shell command. Displayed logs redact the selected source,
output, repository, and home-directory prefixes.

## Verification

```bash
make migration-check
make migration-studio-check
make migration-studio-package
```

`migration-studio-check` runs the UI-independent C++ self-check and a real child
process. The migration test runs the CLI with JSON Lines progress enabled.
Strict verification additionally checks source drift, unresolved reviews,
capability approvals, DSL validity, behavior cases, target binding, signing,
and C++17 VM execution.

The macOS package is currently built and verified by the Apple CI job. The Qt
CMake source also supports Windows and Linux, but their installers and CI
artifacts have not been added yet.
