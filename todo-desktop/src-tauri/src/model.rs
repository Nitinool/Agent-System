use serde::{Deserialize, Serialize};
use ts_rs::TS;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, TS)]
#[serde(deny_unknown_fields)]
pub struct Completion {
    pub completed_at: String,
    pub reopened_at: Option<String>,
    /// 这一条完成记录对应的是哪一天的重复实例；非重复事项为 null。
    pub due_date: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, TS)]
#[serde(deny_unknown_fields)]
pub struct Project {
    pub id: String,
    pub name: String,
    pub color: String,
    pub position: i32,
    pub favorite: bool,
    pub archived: bool,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, TS)]
#[serde(deny_unknown_fields)]
pub struct Section {
    pub id: String,
    pub project_id: String,
    pub name: String,
    pub position: i32,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, TS)]
#[serde(deny_unknown_fields)]
pub struct Label {
    pub id: String,
    pub name: String,
    pub color: String,
    pub position: i32,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, TS)]
#[serde(deny_unknown_fields)]
pub struct Task {
    pub id: String,
    /// `None` 表示收件箱（不属于任何项目）。
    pub project_id: Option<String>,
    pub section_id: Option<String>,
    /// 父事项编号，用于子事项。
    pub parent_id: Option<String>,
    pub title: String,
    pub notes: String,
    pub color: String,
    /// 1 = 最高，4 = 无优先级（与 Todoist 的 p1–p4 一致）。
    pub priority: u8,
    pub start: Option<String>,
    pub end: Option<String>,
    /// 重复规则：`daily` 或 `every:N`；空表示不重复。
    pub recurrence: Option<String>,
    /// 重复到哪一天为止；空表示一直重复。
    pub repeat_until: Option<String>,
    pub position: i32,
    pub completed: bool,
    pub completions: Vec<Completion>,
    pub included_days: Vec<String>,
    pub excluded_days: Vec<String>,
    pub label_ids: Vec<String>,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, TS)]
#[serde(deny_unknown_fields)]
pub struct TaskDraft {
    pub title: String,
    pub notes: String,
    pub color: String,
    pub priority: u8,
    pub start: Option<String>,
    pub end: Option<String>,
    pub recurrence: Option<String>,
    pub repeat_until: Option<String>,
    pub project_id: Option<String>,
    pub section_id: Option<String>,
    pub parent_id: Option<String>,
    pub label_ids: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, TS)]
#[serde(deny_unknown_fields)]
pub struct ProjectDraft {
    pub name: String,
    pub color: String,
    pub favorite: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, TS)]
#[serde(deny_unknown_fields)]
pub struct LabelDraft {
    pub name: String,
    pub color: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, TS)]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
pub enum Mutation {
    TaskSave {
        id: Option<String>,
        draft: TaskDraft,
    },
    TaskComplete {
        id: String,
        completed: bool,
    },
    TaskDelete {
        id: String,
    },
    TaskToday {
        id: String,
        day: String,
        included: bool,
    },
    TaskMove {
        id: String,
        project_id: Option<String>,
        section_id: Option<String>,
        parent_id: Option<String>,
    },
    TaskReorder {
        ids: Vec<String>,
    },
    ProjectSave {
        id: Option<String>,
        draft: ProjectDraft,
    },
    ProjectDelete {
        id: String,
    },
    SectionSave {
        id: Option<String>,
        project_id: String,
        name: String,
    },
    SectionDelete {
        id: String,
    },
    LabelSave {
        id: Option<String>,
        draft: LabelDraft,
    },
    LabelDelete {
        id: String,
    },
}

#[derive(Debug, Clone, Serialize, Deserialize, TS)]
pub struct Snapshot {
    pub revision: u32,
    pub projects: Vec<Project>,
    pub sections: Vec<Section>,
    pub labels: Vec<Label>,
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
    TaskDraft::export_all_to(&folder).unwrap();
    Project::export_all_to(&folder).unwrap();
    ProjectDraft::export_all_to(&folder).unwrap();
    Section::export_all_to(&folder).unwrap();
    Label::export_all_to(&folder).unwrap();
    LabelDraft::export_all_to(&folder).unwrap();
    Completion::export_all_to(&folder).unwrap();
    Mutation::export_all_to(&folder).unwrap();
    Snapshot::export_all_to(&folder).unwrap();
    AppError::export_all_to(&folder).unwrap();
}
