# Agent System V2

Windows 10 / 11 x64 桌面重构版。Tauri 2、Vue 3、TypeScript、Rust 和 SQLite；正式运行不需要 Python。新版六个页面均通过 Rust 服务操作本地数据，不依赖本地 HTTP 服务器。

## 开发环境

- Node.js 24（含 npm）、Rust 1.99.1 MSVC；版本由 `rust-toolchain.toml` 和两个依赖锁文件固定。
- Visual Studio 2022 Build Tools：C++ 桌面工作负载、MSVC 与 Windows SDK。
- Windows WebView2 Runtime。

在本目录执行：

```powershell
npm ci
npm run desktop
```

仓库根目录 `启动桌面新版.cmd` 可协助定位本机工具链。另一台电脑需要独立安装上述开发工具；仓库仅保留这套新版入口。

根目录 `启动现有桌面版.cmd` 是免编译入口，转到 `tools/run-existing.ps1` 直接运行现有 release EXE，不调用 Cargo、npm 或安装器。可以传 `-CheckOnly` 仅检查文件与版本；文件缺失就报错，不自动构建。已有 EXE 属于忽略提交的构建产物，另一台电脑拉取代码后不保证存在；运行内容以该 EXE 的构建时间为准。原开发入口继续用于需要编译和热更新时。日常从资源管理器双击启动，避免 MSIX 宿主隔离资料路径。

如果启动提示“请先安装 Rust MSVC 工具链”，请先运行 [Rust 官方 Windows 安装器](https://rust-lang.org/tools/install/)，选择默认的 `x86_64-pc-windows-msvc` 工具链。安装完成后在本目录执行 `rustup show`，会按 `rust-toolchain.toml` 使用指定版本。Cargo 通常位于 `%USERPROFILE%\.cargo\bin\cargo.exe`，启动脚本会自动加入该目录。

C++ 编译环境需安装完整的 Visual Studio 2022 Build Tools，包含“C++ 生成工具”、MSVC x64 / x86 和 Windows 11 SDK。可以运行 [VS2022 官方安装器](https://aka.ms/vs/17/release/vs_BuildTools.exe)；安装需要 Windows 管理员确认。仅存在 Visual Studio Installer 或安装被中途取消，不表示编译工具已就绪。首次启动还会下载并编译 Rust 依赖，后续启动复用编译缓存。

`tools/develop.ps1` 含中文提示，必须保存为带 BOM 的 UTF-8，以兼容启动入口使用的 Windows PowerShell 5.1；无 BOM 时中文可能被按系统旧编码解析，产生引号 / 语句块错误。PowerShell 7 也可读取带 BOM 的版本。

## 数据与同步

正式数据保存到 `%LOCALAPPDATA%/Agent-System-V2/`，包含 `activity.sqlite3`、`backups/`、`sync-settings.json` 和 DPAPI 加密的 `sync-token.dpapi`。当前数据库版本 2，版本 1 在启动时先完整备份到 `backups/before-upgrade-v1-v2-*.sqlite3`，再事务升级；失败整体回滚。保留既有事项分类、求职及其他业务数据，旧 V2 0.1 构建不能打开升级后的数据库。SQLite 工作线程维护记录、删除标记与同步基线，完成历史及日期关联与事项一起同步。

从 MSIX 打包的开发助手启动子进程时，Windows 可能把同一个 AppData 路径重定向到该助手的私有 LocalCache，造成“助手启动有数据、双击脚本为空”。新版在打开数据库前校验物理目录，拒绝隔离缓存中的资料目录并显示具体启动错误，不自动搬移数据。首次优先从文件资源管理器双击根目录脚本。若此前已有隔离副本，应先关闭程序并完整备份两份数据库，再恢复到正常目录；两边都有记录时必须核对合并，不能直接覆盖。Windows 行为说明见 [Microsoft MSIX 文档](https://learn.microsoft.com/en-us/windows/msix/desktop/desktop-to-uwp-behind-the-scenes)。

2026-10-19 已按用户要求退役旧 Python 工程、本机旧数据及旧同步文件，既有投递记录已核对迁入。日常启动只打开既有新版资料，不扫描或重新导入历史数据库。同步固定使用私有仓库 `Nitinool/Agent-System-data` 中的 **`sync/v2/records.json`**，不得把历史 JSON 复制到该路径。

两台电脑都运行新版后，在侧栏“数据同步”各自配置 Fine-grained Token，仅授权数据仓库的 Contents Read and write。默认手动同步、启动仅检查；需点击“立即同步”才能合并。自动同步需在两台机器分别开启。关闭编辑抽屉并保存输入后再同步；冲突逐条选择或取消，失败保留本机内容，导入前自动备份。行为日志不上传。Token 只在输入框短暂出现，不放入 Pinia、数据库或同步文件；保存凭据由 Rust 调用 Windows DPAPI。

随笔回车 / 确定提交，保留真实提交时间与时区；最近 200 条只限制显示。事项、项目与月历共用记录，完成事件不因重新打开丢失。财务金额使用整数分，待结算不计入到账收入，确认到账更新原记录并按实际日期统计。采集每次启动默认暂停，关闭窗口退出并停止。

## 项目与阶段

- 项目分类默认“其他”。新建事项选项目后带入分类，可单独修改；改项目分类或编辑已有事项不会覆盖已有事项分类。
- 所有页面的共享事项编辑器在选项目后要求同时选阶段；切项目重新选阶段。无项目事项无需阶段。项目页仅在阶段内新增事项；普通阶段含事项（包括完成项）时须先移动 / 删除事项才能删除阶段。
- 每个项目自动创建“未来想法”专用阶段，末尾折叠展示，不可重命名或删除。想法可以不安排日期，通过事项编辑器移入正式阶段。完成项留在原阶段，勾选变淡并排在后面；取消完成保留真实历史。
- 目标型比例只计普通阶段事项，无正式事项显示“暂无正式事项”；探索型累计所有真实完成次数。首页与项目页统计一致，不把投入时长伪造为完成进度，本轮尚未实现采集 / 随笔与项目的时长联动。
- V2 含项目 / 阶段（含删除标记）写同步格式 6，其余仍按既有规则选择格式 1–5。兼容读取格式 1–5，为旧项目补分类与想法阶段、旧无阶段项目事项归入想法；同步基线同步正规化。两台电脑都更新到 0.2.0 后再同步项目新字段。该格式只用于 `sync/v2/records.json`。

## 检查与构建

日常交付默认完成代码修改、必要检查和 GitHub 推送，不自动生成安装包。只有用户明确提出打包要求时，才运行 `npm run bundle` 及安装验证；开发运行、前端构建和 Rust 检查不受影响。

只编译最新可执行程序、不生成安装包时，在 desktop 目录执行 `npm run tauri -- build --no-bundle`。这会编译前端和 Rust，并更新 `src-tauri/target/release/agent-system.exe`；桌面免编译脚本之后直接运行该新程序。命令不会运行 NSIS 或安装器，正式业务数据也不参与编译。

```powershell
npm run build
npm test
npx playwright install chromium
npm run test:e2e
cargo test --manifest-path src-tauri/Cargo.toml --no-default-features
cargo clippy --manifest-path src-tauri/Cargo.toml --no-default-features --all-targets -- -D warnings
cargo check --manifest-path src-tauri/Cargo.toml
# 仅在用户明确要求生成安装包时执行
npm run bundle
```

`npm run bundle` 输出到 `src-tauri/target/release/bundle/nsis/`。安装器按当前用户安装；运行数据独立于安装目录，默认卸载不清除数据。缺少 WebView2 时安装器会下载 Runtime，因此安装过程可能需要联网。本轮没有加入自动更新和代码签名，安装包不包含凭据和个人数据库。

Rust 的 `model.rs` 是前后端契约来源；执行 `npm run types` 再检查生成类型差异。前端组件只通过 `bridge.ts` 中的固定 Tauri 命令与服务通信；不开放任意 SQL、Shell 或文件路径读写。

只在显式 `verification` 功能构建中允许 `--verify-profile <绝对路径>` 指定隔离验证目录；正式安装包不启用该功能。模拟桥接只能用于 Vite 开发模式，生产包无浏览器数据替代或演示初始化。测试使用临时目录，禁止指向真实用户数据。

原生集成检查可对已安装的正式 EXE 执行：`npm run test:native -- "C:\测试安装目录\agent-system.exe"`。脚本仅为子进程指定临时 LOCALAPPDATA / WebView2 目录，通过实际 WebView2 与 Tauri IPC 验证保存、撤销、结算、加密凭据和重启；不导入模拟桥接、不开始真实采集、不使用有效 Token。未传 EXE 时需先 `npm run build:verify`，使用固定读取器验证构建；该测试模式不进入正式安装包。若系统应用控制阻止测试 EXE，保留策略，通过正常安装版验证，不修改系统安全设置。

在原生命令末尾加 `--legacy`，会先在临时目录创建固定的 V2 schema 1 样本，再由实际安装版完成 1→2 升级，核对备份、求职原字段、事项分类与完成历史保留，并重复完整业务和重启流程。该样本仅属于测试脚本，不进入软件日常启动或安装包。

核心性能样本：`cargo run --manifest-path src-tauri/Cargo.toml --no-default-features --example performance`，只使用临时数据库。浏览器界面测试使用隔离的 1,500 个事项 / 150 条今日待办样本，不能把其耗时当作正式桌面性能。`src/bindings/` 由 Rust 生成，其余前端源码使用 Prettier，Rust 使用 rustfmt；依赖、构建产物、测试数据库和截图均不提交。

Windows 用户目录含单引号时，当前 tauri-winres 会错误转义 RC 图标路径。`build.rs` 仅把公开应用图标复制到 `%PUBLIC%/Agent-System-build/<工程路径哈希>/` 后编译，源代码与业务数据不搬动。

## 验收状态

六页、持久化、原生业务流程及当前机器上的安装 / 覆盖升级 / 卸载保留数据已验证。各轮实际结果和未完成环境验证以仓库根目录开发交接文档为准。真实双机同步、硬件锁屏 / 睡眠、干净 Windows 机器和系统级 DPI 尚需补验，不因模拟测试通过而视为已验收。
