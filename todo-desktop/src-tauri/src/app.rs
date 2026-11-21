use crate::{model::*, store::Store};
use std::sync::{Arc, Mutex};
use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Emitter, Manager,
};
use tauri_plugin_notification::NotificationExt;
struct State {
    db: Arc<Mutex<Store>>,
}
/// 启动参数与托盘能力：决定「关窗口是隐藏还是退出」「启动时是否露脸」。
struct Launch {
    hidden: bool,
    tray: bool,
}
/// 记录最近一次弹过提醒的日期，避免同一天重复打扰。
struct Reminder {
    last: Mutex<Option<String>>,
}
fn reminder_tick(app: &tauri::AppHandle) {
    let Ok(directory) = crate::directory::data_directory() else {
        return;
    };
    let Some(time) = crate::settings::load(&directory).reminder_time else {
        return;
    };
    let now = chrono::Local::now();
    if now.format("%H:%M").to_string() != time {
        return;
    }
    let today = now.format("%Y-%m-%d").to_string();
    {
        let reminder = app.state::<Reminder>();
        let Ok(mut last) = reminder.last.lock() else {
            return;
        };
        if last.as_deref() == Some(today.as_str()) {
            return;
        }
        *last = Some(today.clone());
    }
    let state = app.state::<State>();
    let Ok(store) = state.db.lock() else {
        return;
    };
    let Ok((due, overdue)) = store.summary(&today) else {
        return;
    };
    drop(store);
    if due == 0 && overdue == 0 {
        return;
    }
    let mut body = format!("今天还有 {due} 项待办");
    if overdue > 0 {
        body.push_str(&format!("，其中 {overdue} 项已过期"));
    }
    let _ = app
        .notification()
        .builder()
        .title("事项便签")
        .body(body)
        .show();
}
fn interrupted() -> AppError {
    AppError::new("worker", "后台服务暂不可用，请重试。")
}
#[tauri::command]
async fn snapshot(state: tauri::State<'_, State>) -> Result<Snapshot> {
    let db = state.db.clone();
    tauri::async_runtime::spawn_blocking(move || db.lock().map_err(|_| interrupted())?.snapshot())
        .await
        .map_err(|_| interrupted())?
}
#[tauri::command]
async fn mutate(
    app: tauri::AppHandle,
    state: tauri::State<'_, State>,
    mutation: Mutation,
    revision: u32,
) -> Result<Snapshot> {
    let db = state.db.clone();
    let snapshot = tauri::async_runtime::spawn_blocking(move || {
        db.lock()
            .map_err(|_| interrupted())?
            .mutate(mutation, revision)
    })
    .await
    .map_err(|_| interrupted())??;
    // Invalidate both windows only after the SQLite transaction commits.
    let _ = app.emit("tasks-changed", snapshot.revision);
    Ok(snapshot)
}
#[tauri::command]
fn show_main(app: tauri::AppHandle) -> Result<()> {
    show(&app, "main")
}
#[tauri::command]
fn show_sticky(app: tauri::AppHandle) -> Result<()> {
    show(&app, "sticky")
}
fn show(app: &tauri::AppHandle, label: &str) -> Result<()> {
    let window = app.get_webview_window(label).ok_or_else(interrupted)?;
    window.show().map_err(|_| interrupted())?;
    window.unminimize().map_err(|_| interrupted())?;
    window.set_focus().map_err(|_| interrupted())
}
#[tauri::command]
fn set_pinned(app: tauri::AppHandle, pinned: bool) -> Result<()> {
    app.get_webview_window("sticky")
        .ok_or_else(interrupted)?
        .set_always_on_top(pinned)
        .map_err(|_| interrupted())
}
#[tauri::command]
fn app_ready(
    app: tauri::AppHandle,
    launch: tauri::State<'_, Launch>,
    window: tauri::WebviewWindow,
) -> Result<()> {
    // 开机自启带 --hidden，启动时只留在托盘，不弹窗打断。
    if window.label() == "main" && !launch.hidden {
        show(&app, "main")?;
    }
    Ok(())
}
#[tauri::command]
fn quit_app(app: tauri::AppHandle) {
    app.exit(0);
}
#[tauri::command]
async fn trash(state: tauri::State<'_, State>) -> Result<Vec<Task>> {
    let db = state.db.clone();
    tauri::async_runtime::spawn_blocking(move || db.lock().map_err(|_| interrupted())?.trash())
        .await
        .map_err(|_| interrupted())?
}
#[tauri::command]
fn reminder_time() -> Result<Option<String>> {
    let directory = crate::directory::data_directory()?;
    Ok(crate::settings::load(&directory).reminder_time)
}
#[tauri::command]
fn set_reminder_time(time: Option<String>) -> Result<Option<String>> {
    let directory = crate::directory::data_directory()?;
    let mut settings = crate::settings::load(&directory);
    settings.reminder_time = match time {
        Some(value) if !value.trim().is_empty() => Some(crate::settings::checked_time(value.trim())?),
        _ => None,
    };
    crate::settings::save(&directory, &settings)?;
    Ok(settings.reminder_time)
}
#[tauri::command]
fn autostart_enabled() -> Result<bool> {
    Ok(crate::autostart::enabled())
}
#[tauri::command]
fn set_autostart(enabled: bool) -> Result<()> {
    crate::autostart::set(enabled)
}
fn build_tray(app: &tauri::AppHandle) -> tauri::Result<()> {
    let open = MenuItem::with_id(app, "open", "打开事项便签", true, None::<&str>)?;
    let sticky = MenuItem::with_id(app, "sticky", "打开桌面便签", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "退出", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&open, &sticky, &quit])?;
    let mut builder = TrayIconBuilder::new()
        .tooltip("事项便签")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "open" => {
                let _ = show(app, "main");
            }
            "sticky" => {
                let _ = show(app, "sticky");
            }
            "quit" => app.exit(0),
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                let _ = show(tray.app_handle(), "main");
            }
        });
    if let Some(icon) = app.default_window_icon().cloned() {
        builder = builder.icon(icon);
    }
    builder.build(app)?;
    Ok(())
}
pub fn run() {
    let built = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            let _ = show(app, "main");
        }))
        .plugin(tauri_plugin_notification::init())
        .setup(|app| {
            let hidden = std::env::args().any(|arg| arg == "--hidden");
            let directory = crate::directory::data_directory()?;
            std::fs::create_dir_all(&directory)?;
            let db = Store::open(&directory.join("tasks.sqlite3"))?;
            app.manage(State {
                db: Arc::new(Mutex::new(db)),
            });
            let tray = build_tray(app.handle()).is_ok();
            app.manage(Launch { hidden, tray });
            app.manage(Reminder {
                last: Mutex::new(None),
            });
            // 每 30 秒看一次提醒时间，命中且今天还没弹过就提醒一次。
            let handle = app.handle().clone();
            std::thread::spawn(move || loop {
                std::thread::sleep(std::time::Duration::from_secs(30));
                reminder_tick(&handle);
            });
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                let has_tray = window.app_handle().state::<Launch>().tray;
                if has_tray {
                    // 有托盘时关窗口只是收起来，退出走托盘或便签底部的「退出应用」。
                    api.prevent_close();
                    let _ = window.hide();
                } else {
                    window.app_handle().exit(0);
                }
            }
        })
        .invoke_handler(tauri::generate_handler![
            snapshot,
            mutate,
            show_main,
            show_sticky,
            set_pinned,
            app_ready,
            quit_app,
            autostart_enabled,
            set_autostart,
            trash,
            reminder_time,
            set_reminder_time
        ])
        .build(tauri::generate_context!());
    match built {
        Ok(app) => app.run(|_, _| {}),
        Err(error) => {
            rfd::MessageDialog::new()
                .set_title("事项便签启动失败")
                .set_description(error.to_string())
                .set_level(rfd::MessageLevel::Error)
                .show();
        }
    }
}
