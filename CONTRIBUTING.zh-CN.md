# 参与 PVM Runtime

[English](CONTRIBUTING.md)

感谢你改进 PVM Runtime。本仓库需要在 C++17、Python、Android、iOS、
HarmonyOS 和 KMP 之间维护同一份字节码合同，因此一个很小的变更也可能影响多条交付链路。

## 从 Issue 到 PR

1. 先搜索现有 Issue。
2. 选择对应的中文或英文 Issue Form。
3. 非简单代码变更请使用 **PR 方案确认**，等待范围确认后再实现。
4. 从最新 `main` 创建单一目的的分支。
5. 添加能够在回归时失败的最小可运行检查。
6. 创建 PR，并在描述中填写 `Closes #<Issue 编号>`。
7. 处理策略审核、依赖审核、CodeQL 和各平台 CI 的结果。
8. 最后由 CODEOWNER 完成人工审核并合并。

Dependabot 等自动依赖 PR 不要求关联 Issue。

## PR 要求

- 标题采用 Conventional Commit 格式：`类型(范围): 简短摘要`。
- 支持 `build`、`chore`、`ci`、`docs`、`feat`、`fix`、`perf`、
  `refactor`、`release`、`security` 和 `test`。
- 说明根因或用户问题、选择的最小变更、风险、兼容性和验证结果。
- 不要把无关重构与功能修改放在同一个 PR。
- 不得提交私钥、签名文件、令牌、专有 DSL 模块、生产生成包或设备标识。
- Markdown 变更必须在同一个 PR 中同时更新英文和简体中文文件。

## 必需验证

先运行与变更最相关的最小命令，再运行共享门禁：

```bash
make test
make verify-contracts
make docs-check
```

平台变更还应运行对应门禁：

```bash
make android-demo-check
make ios-sdk-check ios-demo-check
make harmony-sdk-check
make kmp-check
```

当变更依赖签名、安全存储、进程生命周期、ABI 加载或厂商 SDK 行为时，
模拟器成功或编译成功不能替代真机证据。

## 文档语言

英文文件使用 `NAME.md`，简体中文文件使用 `NAME.zh-CN.md`。
每对文件都必须互相链接。`make docs-check` 会强制检查文件配对、本地链接和视觉资源。

## 安全漏洞

疑似安全漏洞不得提交普通 Issue。请按照
[SECURITY.zh-CN.md](SECURITY.zh-CN.md) 使用 GitHub Security Advisory。
