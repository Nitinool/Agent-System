use crate::{model::*, store::Store};
use std::sync::{Arc, Mutex};
use tauri::{Emitter, Manager};
struct State {
    db: Arc<Mutex<Store>>,
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
fn app_ready(app: tauri::AppHandle, window: tauri::WebviewWindow) -> Result<()> {
    if window.label() == "main" {
        show(&app, "main")?;
    }
    Ok(())
}
#[tauri::command]
fn quit_app(app: tauri::AppHandle) {
    app.exit(0);
}
pub fn run() {
    let built = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            let _ = show(app, "main");
        }))
        .setup(|app| {
            let directory = crate::directory::data_directory()?;
            std::fs::create_dir_all(&directory)?;
            let db = Store::open(&directory.join("tasks.sqlite3"))?;
            app.manage(State {
                db: Arc::new(Mutex::new(db)),
            });
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                let other = if window.label() == "main" {
                    "sticky"
                } else {
                    "main"
                };
                if window
                    .app_handle()
                    .get_webview_window(other)
                    .is_some_and(|w| w.is_visible().unwrap_or(false))
                {
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
            quit_app
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
