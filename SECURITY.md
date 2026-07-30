# Security Policy

[简体中文](SECURITY.zh-CN.md)

## Reporting a vulnerability

Do not disclose suspected vulnerabilities in public Issues, Discussions, pull
requests, screenshots, or logs.

Repository collaborators should use a
[GitHub Security Advisory](https://github.com/kairowan/PVM-Runtime/security/advisories/new)
draft. Include:

- the affected commit, release, platform, and delivery profile;
- a minimal reproduction using non-production keys and modules;
- the expected and observed security boundary;
- impact and prerequisites;
- any temporary mitigation you have verified.

Never send production private keys, signing files, access tokens, proprietary
business modules, or customer data. Replace them with development fixtures.

## Response

Maintainers will acknowledge a complete report, reproduce it in a private
environment, classify affected versions, and coordinate a fix and disclosure.
Timelines depend on severity, cross-platform impact, and whether vendor SDK or
store coordination is required.

## Supported versions

Security fixes target the current `main` branch and the latest published
release. Older versions should be upgraded unless a maintainer explicitly
announces extended support.

## Security boundaries

PVM Runtime verifies signed modules, enforces release rollback rules, constrains
capabilities, and reduces exposure of business logic. It is not DRM and does
not claim confidentiality on a fully compromised device. See
[the security model](docs/SECURITY_MODEL.md) for the complete boundary.
