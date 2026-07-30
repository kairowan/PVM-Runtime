# 安全策略

[English](SECURITY.md)

## 报告漏洞

请勿在公开 Issue、Discussion、PR、截图或日志中披露疑似漏洞。

仓库协作者请创建
[GitHub Security Advisory](https://github.com/kairowan/PVM-Runtime/security/advisories/new)
草稿，并提供：

- 受影响的提交、版本、平台和交付 Profile；
- 使用开发密钥和非生产模块的最小复现；
- 预期与实际的安全边界；
- 影响和利用前提；
- 已验证的临时缓解方法。

不得发送生产私钥、签名文件、访问令牌、专有业务模块或客户数据。
请使用开发环境夹具替代。

## 响应流程

维护者会确认信息完整的报告，在私密环境中复现，判断受影响版本，
并协调修复与披露。处理时间取决于严重性、跨平台影响，以及是否需要厂商 SDK
或应用商店配合。

## 支持版本

安全修复面向当前 `main` 和最新发布版本。除非维护者明确宣布长期支持，
旧版本应升级到最新版本。

## 安全边界

PVM Runtime 会验证签名模块、执行 release 防回滚、限制 Capability，
并降低业务逻辑暴露程度。它不是 DRM，也不承诺设备完全失陷后仍然保密。
完整边界见[安全模型](docs/SECURITY_MODEL.zh-CN.md)。
