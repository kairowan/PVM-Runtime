[English](MIGRATION_STUDIO.md)

# PVM Migration Studio

PVM Migration Studio 是用于选择性迁移的 C++17/Qt 桌面前端。它没有另写一套迁移
引擎：扫描、转换和验证调用的仍是命令行与 CI 共用的扫描器、转换器、DSL 编译器、
Host IDL 检查、签名器和 C++17 VM。

![PVM Migration Studio 完成真实转换和验证](assets/migration-studio.png)

## 使用流程

1. 选择老项目源码目录和当前仓库内的输出目录。
2. 添加一个或多个类/模块选择器。程序不会隐式转换整个项目。
3. 执行**扫描**，检查选中声明、依赖、风险提示和建议 Capability。
4. 执行**转换**，生成 DSL 骨架和待复核文件。
5. 在**复核**页修改批准项、Capability、行为用例和 DSL。JSON 会先校验，再原子保存。
6. 补充复核结论期间执行**结构验证**。
7. 接受迁移前，使用目标绑定、Runtime 和签名密钥执行**严格验证**。

进度条消费迁移后端发出的 JSON Lines 事件，显示的是真实阶段，不是定时动画。当前
操作可以取消；带颜色且有容量上限的日志可以复制或导出。

```mermaid
flowchart LR
  UI["Migration Studio<br/>选择范围、复核、日志"] --> Engine["现有迁移引擎"]
  Engine --> Source["源码快照<br/>风险与依赖报告"]
  Engine --> Review["批准项、Capability<br/>与行为用例"]
  Engine --> DSL["生成的 PVM DSL"]
  DSL --> Compiler["DSL 编译器 + Host IDL"]
  Compiler --> VM["签名模块 + C++17 VM 验证"]
  Review --> VM
```

## 构建与运行

从仓库根目录执行：

```bash
make migration-studio-package
make migration-studio-run
```

下载内容、源码、构建缓存和产物都留在当前仓库：

| 路径 | 用途 |
|---|---|
| `tools/migration-studio/` | C++17/Qt 应用源码 |
| `third_party/qt/6.12.0/` | 仓库内固定版本的 Qt SDK |
| `build/migration-studio-tools/` | 仓库内的 `aqtinstall` 与下载归档 |
| `build/migration-studio/` | CMake 构建目录 |
| `dist/desktop/PVMMigrationStudio.app` | 可移动的 macOS 开发包 |
| `build/migration-studio-output/` | 默认迁移输出 |

安装脚本只下载需要的 Qt Base 归档。macOS 应用动态链接随包携带的 Qt Framework，
并包含对应的 Qt 许可和 NOTICE 文件。

## 随包运行环境

macOS 应用包内包含迁移 Python 后端、JSON 规范、C++17 `pvm_cli` 和 Qt Runtime，
不会携带开发私钥。当前转换、签名和严格验证仍要求宿主提供 Python 3.9+ 与 OpenSSL。

后端进程通过 `QProcess` 接收参数数组，不会把源码路径拼接成 Shell 命令。界面日志
会隐藏所选源码、输出、仓库和用户主目录的路径前缀。

## 验证

```bash
make migration-check
make migration-studio-check
make migration-studio-package
```

`migration-studio-check` 会运行与界面无关的 C++ 自检和真实子进程；迁移测试会启用
JSON Lines 进度并调用真实 CLI。严格验证还会检查源码漂移、未完成复核、Capability
批准、DSL 合法性、行为用例、目标绑定、签名和 C++17 VM 执行。

Apple CI 当前会构建和验证 macOS 应用包。Qt/CMake 源码也支持 Windows 和 Linux，
但这两个平台的安装包与 CI 产物尚未加入。
