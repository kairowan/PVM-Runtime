# Contributing to PVM Runtime

[简体中文](CONTRIBUTING.zh-CN.md)

Thank you for improving PVM Runtime. This repository protects a shared bytecode
contract across C++17, Python, Android, iOS, HarmonyOS, and KMP, so even a small
change can affect more than one delivery path.

## Issue-to-PR workflow

1. Search existing Issues.
2. Open the appropriate English or Chinese Issue Form.
3. For non-trivial code changes, use **PR proposal** and wait for scope
   confirmation.
4. Create a focused branch from the latest `main`.
5. Add the smallest runnable check that would fail if the change regresses.
6. Open a PR and include `Closes #<issue-number>` in its description.
7. Address the automated policy, dependency, CodeQL, and platform CI reviews.
8. A CODEOWNER performs the final human review and merges the PR.

Automated dependency PRs are exempt from the linked-Issue requirement.

## Pull-request requirements

- Use a Conventional Commit style title:
  `type(scope): concise summary`.
- Supported types are `build`, `chore`, `ci`, `docs`, `feat`, `fix`, `perf`,
  `refactor`, `release`, `security`, and `test`.
- Explain the root cause or user problem, the smallest chosen change, risk,
  compatibility, and verification.
- Do not combine unrelated refactors with a functional change.
- Do not commit private keys, signing files, tokens, proprietary DSL modules,
  generated production packages, or device identifiers.
- Update both English and Simplified Chinese Markdown files in the same PR.

## Required verification

Run the narrowest relevant command first, then the shared gates:

```bash
make test
make verify-contracts
make docs-check
```

Platform changes should also run their corresponding gate:

```bash
make android-demo-check
make ios-sdk-check ios-demo-check
make harmony-sdk-check
make kmp-check
```

Simulator or compiler success is not a substitute for physical-device evidence
when the change depends on signing, secure storage, process lifecycle, ABI
loading, or vendor SDK behavior.

## Documentation languages

English is stored in `NAME.md`; Simplified Chinese is stored in
`NAME.zh-CN.md`. Every pair must link to the other language. `make docs-check`
enforces the pairing and validates local links and visual assets.

## Security reports

Do not open public Issues for suspected vulnerabilities. Follow
[SECURITY.md](SECURITY.md) and use GitHub Private Vulnerability Reporting.

