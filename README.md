# Agent System

Windows 10 / 11 x64 个人记录与行动管理应用，仅保留 Tauri 2 / Vue 3 / TypeScript / Rust 新版，不需要 Python。

## 启动

双击根目录 **启动桌面新版.cmd**。开发环境需要 Node.js 24、Rust 1.99.1 MSVC、Visual Studio 2022 C++ Build Tools / Windows SDK 和 WebView2，安装与排障见 [desktop/README.md](desktop/README.md)。

也可以在 desktop 目录执行：

```powershell
npm ci
npm run desktop
```

脚本启动开发模式，会使用本机编译缓存；关闭窗口会退出应用。没有明确要求时不生成安装包。

## 功能

- 今日：随笔快捷记录、今日待办、当月收支、进行中的项目与按应用统计的时间饼图。
- 事项与项目：月历、日期范围安排、阶段、目标型 / 探索型进度、分类及真实完成历史。
- 求职：已投岗位、进度、面试 / 笔试 / 拒绝时间与备注。
- 财务：整数分记账、副业收入及待结算。
- 时间记录：Windows 前台应用采集，每次启动默认暂停。

## 数据与同步

本机正式资料位于 **%LOCALAPPDATA%/Agent-System-V2/**，包含 activity.sqlite3、backups、sync-settings.json 和 DPAPI 加密的 sync-token.dpapi。代码仓库不保存个人数据或 Token。

两台电脑在“数据同步”中各自配置仅授权私有仓库 Nitinool/Agent-System-data 的 Fine-grained Token，Contents 权限为 Read and write。新版只同步 **sync/v2/records.json**；默认手动同步，启动检查不会自动导入。换电脑前完成同步，另一台先同步再编辑。

从 MSIX 开发助手启动时，AppData 可能被重定向；启动会核对物理目录，防止使用另一份隔离数据库。首次优先从文件资源管理器双击脚本。异常时先保留窗口与数据，不删除数据库或重复初始化。

2026-10-19 起旧 Python 代码、测试、入口与本机旧数据退役，既有投递记录已核对迁入新版。历史同步文件不再作为数据来源。

## 开发

[项目结构.md](项目结构.md) 说明当前目录与边界；[开发交接.md](开发交接.md) 记录当前进度、验证和待办。两台电脑交替开发时先读取 [AGENTS.md](AGENTS.md)，拉取最新 main，完成后更新交接并提交推送。

检查命令、数据库升级、同步兼容与按需打包说明见 [desktop/README.md](desktop/README.md)。
