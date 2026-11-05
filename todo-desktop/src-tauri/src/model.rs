use serde::{Deserialize, Serialize};
use ts_rs::TS;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, TS)]
#[serde(deny_unknown_fields)]
pub struct Completion {
    pub completed_at: String,
    pub reopened_at: Option<String>,
}
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, TS)]
#[serde(deny_unknown_fields)]
pub struct Task {
    pub id: String,
    pub title: String,
    pub start: Option<String>,
    pub end: Option<String>,
    pub category: String,
    pub color: String,
    pub notes: String,
    pub completed: bool,
    pub completions: Vec<Completion>,
    pub included_days: Vec<String>,
    pub excluded_days: Vec<String>,
    pub created_at: String,
    pub updated_at: String,
}
#[derive(Debug, Clone, Serialize, Deserialize, TS)]
#[serde(deny_unknown_fields)]
pub struct Draft {
    pub title: String,
    pub start: Option<String>,
    pub end: Option<String>,
    pub category: String,
    pub color: String,
    pub notes: String,
}
#[derive(Debug, Clone, Serialize, Deserialize, TS)]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
pub enum Mutation {
    Save {
        id: Option<String>,
        draft: Draft,
    },
    Complete {
        id: String,
        completed: bool,
    },
    Delete {
        id: String,
    },
    Today {
        id: String,
        day: String,
        included: bool,
    },
}
#[derive(Debug, Clone, Serialize, Deserialize, TS)]
pub struct Snapshot {
    pub revision: u32,
    pub tasks: Vec<Task>,
}
#[derive(Debug, Clone, Serialize, TS)]
pub struct AppError {
    pub code: String,
    pub message: String,
}
pub type Result<T> = std::result::Result<T, AppError>;
impl AppError {
    pub fn new(code: &str, message: &str) -> Self {
        Self {
            code: code.into(),
            message: message.into(),
        }
    }
}
impl std::fmt::Display for AppError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}
impl std::error::Error for AppError {}
impl From<rusqlite::Error> for AppError {
    fn from(_: rusqlite::Error) -> Self {
        Self::new("database", "数据库操作失败，请检查目录权限或磁盘空间。")
    }
}
impl From<std::io::Error> for AppError {
    fn from(_: std::io::Error) -> Self {
        Self::new("io", "无法访问事项便签数据目录。")
    }
}
impl From<serde_json::Error> for AppError {
    fn from(_: serde_json::Error) -> Self {
        Self::new("data", "事项数据格式损坏，已停止操作，请保留数据文件。")
    }
}

#[cfg(test)]
#[test]
fn export_bindings() {
    let folder = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../src/bindings");
    Task::export_all_to(&folder).unwrap();
    Draft::export_all_to(&folder).unwrap();
    Mutation::export_all_to(&folder).unwrap();
    Snapshot::export_all_to(&folder).unwrap();
    AppError::export_all_to(&folder).unwrap();
}
