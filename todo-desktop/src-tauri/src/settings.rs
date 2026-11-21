// 本地设置：目前只有每日提醒时间，放在数据目录的 settings.json。
use crate::model::{AppError, Result};
use serde::{Deserialize, Serialize};
use std::path::Path;

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Settings {
    #[serde(default)]
    pub reminder_time: Option<String>,
    #[serde(default)]
    pub sync_last_at: Option<String>,
    #[serde(default)]
    pub sync_last_message: Option<String>,
}

fn file(directory: &Path) -> std::path::PathBuf {
    directory.join("settings.json")
}

pub fn load(directory: &Path) -> Settings {
    std::fs::read_to_string(file(directory))
        .ok()
        .and_then(|text| serde_json::from_str(&text).ok())
        .unwrap_or_default()
}

pub fn save(directory: &Path, settings: &Settings) -> Result<()> {
    let text = serde_json::to_string_pretty(settings)?;
    std::fs::write(file(directory), text)?;
    Ok(())
}

/// 校验 `HH:MM`（24 小时制），返回归一化后的值。
pub fn checked_time(value: &str) -> Result<String> {
    let parsed = chrono::NaiveTime::parse_from_str(value, "%H:%M")
        .map_err(|_| AppError::new("validation", "提醒时间格式应为 HH:MM。"))?;
    Ok(parsed.format("%H:%M").to_string())
}
