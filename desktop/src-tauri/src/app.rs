//! Tauri composition and narrow IPC boundary. Blocking work stays off the event loop.
use crate::{model::*, store::Database, sync::SyncService};
use std::{
    collections::BTreeMap,
    path::PathBuf,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
    time::{Duration, Instant},
};
use tauri::{Emitter, Manager};

struct CaptureService {
    status: Arc<Mutex<CaptureStatus>>,
    stopping: Arc<AtomicBool>,
    worker: Mutex<Option<std::thread::JoinHandle<()>>>,
}
impl CaptureService {
    fn start(db: Database, app: tauri::AppHandle) -> Result<Self> {
        let status = Arc::new(Mutex::new(CaptureStatus {
            running: false,
            message: "已暂停 · 点击开始记录".into(),
            exclusions: String::new(),
        }));
        let stopping = Arc::new(AtomicBool::new(false));
        let thread_status = status.clone();
        let thread_stopping = stopping.clone();
        let next = db.call(|s| {
            Ok(s.db
                .query_row("SELECT COALESCE(MAX(id),0)+1 FROM segments", [], |r| {
                    r.get(0)
                })?)
        })?;
        let worker = std::thread::Builder::new()
            .name("foreground-sampler".into())
            .spawn(move || {
                let mut recorder = crate::capture::Recorder::new(next);
                let clock = Instant::now();
                let mut next = Instant::now();
                let mut samples = 0u32;
                let mut previous_exclusions = String::new();
                while !thread_stopping.load(Ordering::SeqCst) {
                    let state = thread_status.lock().unwrap().clone();
                    if !state.running || state.exclusions != previous_exclusions {
                        let rows = recorder.stop(if state.exclusions != previous_exclusions {
                            "修改排除进程"
                        } else {
                            "暂停记录"
                        });
                        if !rows.is_empty() {
                            let _ = db.call(move |s| s.save_segments(&rows));
                            let _ = app.emit("capture-changed", ());
                        }
                        previous_exclusions = state.exclusions.clone();
                    }
                    if state.running && Instant::now() >= next {
                        next = Instant::now() + Duration::from_secs(1);
                        #[cfg(feature = "verification")]
                        let fixed = std::env::args().any(|s| s == "--fixed-reader");
                        #[cfg(not(feature = "verification"))]
                        let fixed = false;
                        let (activity, locked) = if fixed {
                            (
                                Some(crate::capture::Activity {
                                    pid: 99999,
                                    process: "fixture.exe".into(),
                                    title: "固定测试窗口".into(),
                                    own: false,
                                }),
                                Some(false),
                            )
                        } else {
                            crate::platform::observation()
                        };
                        let excluded: Vec<_> = state
                            .exclusions
                            .replace('，', ",")
                            .split(',')
                            .map(|s| s.trim().to_lowercase())
                            .filter(|s| !s.is_empty())
                            .collect();
                        let old = recorder.active.as_ref().map(|s| s.id);
                        let result = recorder
                            .sample(
                                activity,
                                locked,
                                &excluded,
                                &chrono::Local::now().to_rfc3339(),
                                clock.elapsed().as_secs_f64(),
                            )
                            .and_then(|rows| db.call(move |s| s.save_segments(&rows)));
                        let mut status = thread_status.lock().unwrap();
                        if let Err(e) = result {
                            status.running = false;
                            status.message = e.message;
                        } else {
                            status.message = match locked {
                                Some(true) => "正在记录 · 已锁屏",
                                Some(false) => "正在记录",
                                None => "会话状态不可读取，等待恢复",
                            }
                            .into();
                        }
                        samples += 1;
                        if samples % 5 == 0 || old != recorder.active.as_ref().map(|s| s.id) {
                            let _ = app.emit("capture-changed", ());
                        }
                    }
                    std::thread::sleep(Duration::from_millis(100));
                }
                let rows = recorder.stop("关闭软件");
                let _ = db.call(move |s| s.save_segments(&rows));
            })?;
        Ok(Self {
            status,
            stopping,
            worker: Mutex::new(Some(worker)),
        })
    }
    fn shutdown(&self) {
        self.stopping.store(true, Ordering::SeqCst);
        if let Some(worker) = self.worker.lock().unwrap().take() {
            let _ = worker.join();
        }
    }
}
struct AppState {
    db: Database,
    sync: SyncService,
    capture: CaptureService,
    stopping: Arc<AtomicBool>,
}
fn interrupted() -> AppError {
    AppError::new("interrupted", "后台操作已中断，请重试。")
}

#[tauri::command]
async fn snapshot(state: tauri::State<'_, AppState>) -> Result<Snapshot> {
    let db = state.db.clone();
    tauri::async_runtime::spawn_blocking(move || db.call(|s| s.snapshot()))
        .await
        .map_err(|_| interrupted())?
}
#[tauri::command]
async fn mutate(
    state: tauri::State<'_, AppState>,
    app: tauri::AppHandle,
    mutation: Mutation,
    expected_revision: u32,
) -> Result<Snapshot> {
    let db = state.db.clone();
    let result = tauri::async_runtime::spawn_blocking(move || {
        db.call(move |s| s.mutate(mutation, expected_revision))
    })
    .await
    .map_err(|_| interrupted())??;
    let _ = app.emit("data-changed", result.revision);
    Ok(result)
}
#[tauri::command]
async fn segments(state: tauri::State<'_, AppState>, day: Option<String>) -> Result<Vec<Segment>> {
    let db = state.db.clone();
    tauri::async_runtime::spawn_blocking(move || db.call(move |s| s.segments(day.as_deref())))
        .await
        .map_err(|_| interrupted())?
}
#[tauri::command]
async fn classify(
    state: tauri::State<'_, AppState>,
    app: tauri::AppHandle,
    ids: Vec<i64>,
    category: String,
) -> Result<()> {
    let db = state.db.clone();
    tauri::async_runtime::spawn_blocking(move || db.call(move |s| s.classify(&ids, &category)))
        .await
        .map_err(|_| interrupted())??;
    let _ = app.emit("capture-changed", ());
    Ok(())
}
#[tauri::command]
fn capture_status(state: tauri::State<'_, AppState>) -> CaptureStatus {
    state.capture.status.lock().unwrap().clone()
}
#[tauri::command]
fn capture_control(
    state: tauri::State<'_, AppState>,
    app: tauri::AppHandle,
    running: bool,
    exclusions: String,
) -> CaptureStatus {
    let mut s = state.capture.status.lock().unwrap();
    s.running = running;
    s.exclusions = exclusions;
    s.message = if running { "正在记录" } else { "已暂停" }.into();
    let result = s.clone();
    drop(s);
    let _ = app.emit("capture-changed", ());
    result
}
#[tauri::command]
async fn sync_status(state: tauri::State<'_, AppState>) -> Result<SyncStatus> {
    let sync = state.sync.clone();
    tauri::async_runtime::spawn_blocking(move || sync.status())
        .await
        .map_err(|_| interrupted())?
}
#[tauri::command]
async fn sync_configure(
    state: tauri::State<'_, AppState>,
    settings: SyncSettings,
    token: Option<String>,
    remember: bool,
    forget: bool,
) -> Result<SyncStatus> {
    let sync = state.sync.clone();
    tauri::async_runtime::spawn_blocking(move || sync.configure(settings, token, remember, forget))
        .await
        .map_err(|_| interrupted())?
}
#[tauri::command]
async fn sync_run(
    state: tauri::State<'_, AppState>,
    app: tauri::AppHandle,
    choices: BTreeMap<String, String>,
) -> Result<SyncStatus> {
    let sync = state.sync.clone();
    let result = tauri::async_runtime::spawn_blocking(move || sync.run(false, false, choices))
        .await
        .map_err(|_| interrupted())?;
    let _ = app.emit("sync-changed", ());
    result
}
#[tauri::command]
fn sync_cancel(state: tauri::State<'_, AppState>) {
    state.sync.cancel_conflicts()
}
#[tauri::command]
fn set_editing(state: tauri::State<'_, AppState>, editing: bool) {
    state.sync.editing.store(editing, Ordering::SeqCst)
}
#[tauri::command]
fn app_ready(window: tauri::WebviewWindow) -> Result<()> {
    window
        .show()
        .map_err(|_| AppError::new("window", "窗口无法显示。"))
}
#[tauri::command]
fn open_token_page() -> Result<()> {
    crate::platform::open_url("https://github.com/settings/personal-access-tokens/new")
}
#[tauri::command]
async fn open_job_url(state: tauri::State<'_, AppState>, uid: String) -> Result<()> {
    let db = state.db.clone();
    let url = tauri::async_runtime::spawn_blocking(move || {
        db.call(move |s| {
            let snapshot = s.snapshot()?;
            match snapshot.records.get(&uid) {
                Some(Record::Job(Some(j))) => Ok(j.url.clone()),
                _ => Err(AppError::validation("岗位已不存在。")),
            }
        })
    })
    .await
    .map_err(|_| interrupted())??;
    crate::platform::open_url(&url)
}
#[tauri::command]
async fn export_csv(
    state: tauri::State<'_, AppState>,
    day: Option<String>,
    merged: bool,
) -> Result<Option<String>> {
    let db = state.db.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let rows = db.call(move |s| s.segments(day.as_deref()))?;
        let rows = if merged {
            crate::capture::merge_display(rows)
        } else {
            rows
        };
        if let Some(path) = rfd::FileDialog::new()
            .add_filter("CSV", &["csv"])
            .set_file_name("行为日志.csv")
            .save_file()
        {
            std::fs::write(&path, crate::capture::csv(&rows))?;
            Ok(Some(path.to_string_lossy().into_owned()))
        } else {
            Ok(None)
        }
    })
    .await
    .map_err(|_| interrupted())?
}
fn directory() -> Result<PathBuf> {
    #[cfg(feature = "verification")]
    {
        let args: Vec<_> = std::env::args_os().collect();
        if let Some(i) = args.iter().position(|s| s == "--verify-profile") {
            let path = PathBuf::from(
                args.get(i + 1)
                    .ok_or_else(|| AppError::validation("缺少验证目录。"))?,
            );
            if !path.is_absolute() {
                return Err(AppError::validation("验证目录必须是绝对路径。"));
            }
            return Ok(path);
        }
    }
    Ok(PathBuf::from(
        std::env::var_os("LOCALAPPDATA")
            .ok_or_else(|| AppError::new("directory", "无法确定本机数据目录。"))?,
    )
    .join("Agent-System-V2"))
}
pub fn run() {
    let result = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.show();
                let _ = w.set_focus();
            }
        }))
        .setup(|app| {
            let directory = directory()?;
            std::fs::create_dir_all(&directory)?;
            let db = Database::start(directory.join("activity.sqlite3"))?;
            let sync = SyncService::new(db.clone(), directory)?;
            let capture = CaptureService::start(db.clone(), app.handle().clone())?;
            let stopping = Arc::new(AtomicBool::new(false));
            let flag = stopping.clone();
            let service = sync.clone();
            let handle = app.handle().clone();
            std::thread::Builder::new()
                .name("sync-scheduler".into())
                .spawn(move || {
                    std::thread::sleep(Duration::from_millis(700));
                    let mut startup = true;
                    while !flag.load(Ordering::SeqCst) {
                        let result = service.background_tick(startup);
                        startup = false;
                        if result.as_ref().is_ok_and(|r| *r) || result.is_err() {
                            let _ = handle.emit("sync-changed", ());
                        }
                        for _ in 0..30 {
                            if flag.load(Ordering::SeqCst) {
                                return;
                            }
                            std::thread::sleep(Duration::from_millis(100));
                        }
                    }
                })?;
            app.manage(AppState {
                db,
                sync,
                capture,
                stopping,
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            snapshot,
            mutate,
            segments,
            classify,
            capture_status,
            capture_control,
            sync_status,
            sync_configure,
            sync_run,
            sync_cancel,
            set_editing,
            app_ready,
            open_token_page,
            open_job_url,
            export_csv
        ])
        .build(tauri::generate_context!());
    match result {
        Ok(app) => app.run(|handle, event| {
            if let tauri::RunEvent::ExitRequested { .. } = event {
                if let Some(state) = handle.try_state::<AppState>() {
                    state.stopping.store(true, Ordering::SeqCst);
                    state.capture.shutdown();
                }
            }
        }),
        Err(_) => {
            rfd::MessageDialog::new().set_title("Agent System 启动失败").set_description("新版无法启动，请检查本机数据目录权限、数据库或 WebView2 环境。旧版数据未被修改。").set_level(rfd::MessageLevel::Error).show();
        }
    }
}
