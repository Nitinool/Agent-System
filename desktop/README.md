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

仓库根目录 `启动桌面新版.cmd` 可协助定位本机工具链。另一台电脑需要独立安装上述开发工具；Python 旧版入口继续保留。

## 数据与同步

正式数据保存到 `%LOCALAPPDATA%/Agent-System-V2/`，包含 `activity.sqlite3`、`backups/`、`sync-settings.json` 和 DPAPI 加密的 `sync-token.dpapi`。空数据库版本 1，使用有类型的业务记录和稳定全局编号，SQLite 工作线程在事务中维护记录、删除标记与同步基线。完成历史及日期关联保存在对应事项中，与同步中的原子记录边界一致。

新版从空数据开始，不扫描、导入或删除旧版数据库。旧版的 `data/`、启动入口和 `sync/records.json` 不变。新版同步固定使用私有仓库 `Nitinool/Agent-System-data` 中的 **`sync/v2/records.json`**；不要把旧文件复制到新版路径。

两台电脑都运行新版后，在侧栏“数据同步”各自配置 Fine-grained Token，仅授权数据仓库的 Contents Read and write。默认手动同步、启动仅检查；需点击“立即同步”才能合并。自动同步需在两台机器分别开启。关闭编辑抽屉并保存输入后再同步；冲突逐条选择或取消，失败保留本机内容，导入前自动备份。行为日志不上传。Token 只在输入框短暂出现，不放入 Pinia、数据库或同步文件；保存凭据由 Rust 调用 Windows DPAPI。

随笔回车 / 确定提交，保留真实提交时间与时区；最近 200 条只限制显示。事项、项目与月历共用记录，完成事件不因重新打开丢失。财务金额使用整数分，待结算不计入到账收入，确认到账更新原记录并按实际日期统计。采集每次启动默认暂停，关闭窗口退出并停止。

## 检查与构建

```powershell
npm run build
npm test
npx playwright install chromium
npm run test:e2e
cargo test --manifest-path src-tauri/Cargo.toml --no-default-features
cargo check --manifest-path src-tauri/Cargo.toml
npm run bundle
```

`npm run bundle` 输出到 `src-tauri/target/release/bundle/nsis/`。安装器按当前用户安装；运行数据独立于安装目录，默认卸载不清除数据。缺少 WebView2 时安装器会下载 Runtime，因此安装过程可能需要联网。本轮没有加入自动更新和代码签名，安装包不包含凭据和个人数据库。

Rust 的 `model.rs` 是前后端契约来源；执行 `npm run types` 再检查生成类型差异。前端组件只通过 `bridge.ts` 中的固定 Tauri 命令与服务通信；不开放任意 SQL、Shell 或文件路径读写。

只在显式 `verification` 功能构建中允许 `--verify-profile <绝对路径>` 指定隔离验证目录；正式安装包不启用该功能。模拟桥接只能用于 Vite 开发模式，生产包无浏览器数据替代或演示初始化。测试使用临时目录，禁止指向真实用户数据。

Windows 用户目录含单引号时，当前 tauri-winres 会错误转义 RC 图标路径。`build.rs` 仅把公开应用图标复制到 `%PUBLIC%/Agent-System-build/<工程路径哈希>/` 后编译，源代码与业务数据不搬动。

## 验收状态

各轮实际结果和未完成环境验证以仓库根目录开发交接文档为准。尚未完成验证的安装、真实双机、锁屏 / 睡眠等场景，不因模拟测试通过而视为已验收。
