# 事项便签

独立的 Windows 10 / 11 x64 事项与待办应用。沿用 Agent System 的浅色月历与紧凑事项列表风格，单独编译、单独运行，不依赖原应用或其数据。

## 使用

- 左侧栏在收件箱、今天、接下来、月历、全部之间切换，并按项目、标签分组查看。
- 事项支持项目、分区、多个标签、优先级 P1–P4、子事项、颜色、备注、日期范围、搜索与待安排，可拖拽调整顺序。
- 所有新增入口默认安排在本地今天，即便当前月历选中了其他日期。结束日期留空表示单日；可选择日期范围，或清除日期留待安排。
- 今日待办按当天日期筛选。范围内每天显示；完成后保留勾选和划线，可取消完成或手动隐藏。移出今天仅排除当天；全部事项里可以重新加入今天。
- 点击“便签”打开独立桌面小窗口，只列今日待办；可置顶 / 取消置顶、直接勾选和返回主窗口。两个窗口实时联动，跨午夜和睡眠唤醒后按本地日期更新。
- 便签打开时关闭主窗口会继续保留便签；关闭最后一个可见窗口或点击便签底部“退出应用”会结束程序。再次打开应用可唤回主窗口。

双击本目录 **启动.cmd**，或仓库根目录 **启动事项便签.cmd**，运行已经编译好的程序，不重新编译。没有 EXE 时会明确提示先构建。当前使用嵌入界面的 debug EXE；可单独运行，不需要 Node、Rust 或业务服务器，电脑须有 WebView2。

## 数据

资料独立保存在 **%LOCALAPPDATA%/Task-Notes/tasks.sqlite3**（SQLite schema 2，正表化）。不读取或写入 Agent-System-V2，不导入已有事项，不使用原应用的同步 Token 或远端文件。本版只做本机持久化，尚未提供跨电脑同步。

schema 1 旧库首次打开会自动升级：先把数据库（含 WAL 内容）备份到 `backups/tasks-<时间戳>.sqlite3`，再在单事务里正表化；旧「分类」迁成标签，旧事项进收件箱，日期范围与「加入 / 移出今天」的行为不变。升级失败会回滚并保留备份，不会带着半份数据继续用。

SQLite 事务保存；主窗口 / 便签共用一个后台资料服务，通过版本号拒绝过期写入，失败显示错误并保留编辑内容。完成 / 取消完成保留真实历史时间。MSIX 重定向目录会被拒绝，避免产生两份资料；请优先从文件资源管理器双击启动。

## 开发和验证

Node 24、Rust 1.99.1 MSVC、Windows C++ Build Tools / SDK 和 WebView2，与原工程使用相同工具链；本目录可以单独复制开发。没有对 ../desktop 的源码或运行依赖。

```powershell
npm ci
npm run desktop
# 编译可直接运行的程序，不生成安装包
powershell -NoProfile -ExecutionPolicy Bypass -File tools/start.ps1 -Build
# 检查已有程序
powershell -NoProfile -ExecutionPolicy Bypass -File tools/start.ps1 -CheckOnly
```

构建后将嵌入界面的程序复制到 bin/task-notes.exe，日常入口固定运行该文件；后续开发构建不会把它替换成依赖 Vite 的开发程序。开发模式使用端口 1431，与原应用的端口不同。仓库根目录“开发事项便签.cmd”也可打开开发模式。tools/start.ps1 含中文，保存为 UTF-8 BOM，兼容 Windows PowerShell 5.1。

```powershell
npm run build
npm test
cargo test --manifest-path src-tauri/Cargo.toml --no-default-features
cargo clippy --manifest-path src-tauri/Cargo.toml --all-targets -- -D warnings
npm run test:native
```

model.rs 为契约来源，npm run types 生成 src/bindings，不手工编辑。native-smoke.mjs 在工程内创建隔离 LOCALAPPDATA / WebView2 目录，只向临时库写固定样本，测试真实双窗口、日期、跨天、完成 / 撤销、删除和重启；不接触日常数据。测试截图和临时资料不提交。

未生成安装包；开机启动、托盘、自定义透明便签尚未实现。真实系统睡眠 / 唤醒、干净 Windows 与系统 DPI 尚未全面验收。
