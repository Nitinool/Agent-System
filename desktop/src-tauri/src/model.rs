//! Shared wire types. JSON field names intentionally match the existing sync format.
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use ts_rs::TS;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, TS)]
#[serde(deny_unknown_fields)]
pub struct Project {
    pub name: String,
    pub goal: String,
    pub status: String,
    pub priority: String,
    pub mode: String,
}
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, TS)]
#[serde(deny_unknown_fields)]
pub struct Milestone {
    pub project_id: String,
    pub name: String,
    pub acceptance: String,
    pub position: u32,
    pub completed_at: Option<String>,
}
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, TS)]
#[serde(deny_unknown_fields)]
pub struct Completion {
    pub title: String,
    pub project_id: Option<String>,
    pub completed_at: String,
    pub reopened_at: Option<String>,
}
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, TS)]
#[serde(deny_unknown_fields)]
pub struct Task {
    pub title: String,
    pub planned_on: Option<String>,
    pub category: String,
    pub notes: String,
    pub status: String,
    pub priority: String,
    pub kind: String,
    pub project_id: Option<String>,
    pub resume_status: String,
    pub milestone_id: Option<String>,
    pub acceptance: String,
    pub outcome: String,
    pub completed_at: Option<String>,
    pub range_start: Option<String>,
    pub range_end: Option<String>,
    pub excluded_days: Vec<String>,
    pub days: Vec<String>,
    pub completions: Vec<Completion>,
}
impl Default for Task {
    fn default() -> Self {
        Self {
            title: String::new(),
            planned_on: None,
            category: "其他".into(),
            notes: String::new(),
            status: "待开始".into(),
            priority: "普通".into(),
            kind: "任务".into(),
            project_id: None,
            resume_status: "待开始".into(),
            milestone_id: None,
            acceptance: String::new(),
            outcome: String::new(),
            completed_at: None,
            range_start: None,
            range_end: None,
            excluded_days: vec![],
            days: vec![],
            completions: vec![],
        }
    }
}
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, TS)]
#[serde(deny_unknown_fields)]
pub struct Note {
    pub title: String,
    pub created_at: String,
}
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, TS)]
#[serde(deny_unknown_fields)]
pub struct Job {
    pub company: String,
    pub title: String,
    pub applied_on: String,
    pub status: String,
    pub url: String,
    pub notes: String,
    pub interview_at: String,
    pub written_at: String,
    pub rejected_at: String,
}
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, TS)]
#[serde(deny_unknown_fields)]
pub struct Finance {
    pub direction: String,
    #[ts(type = "number")]
    pub amount_cents: i64,
    pub occurred_on: String,
    pub title: String,
    pub category: String,
    pub side_source: String,
    pub status: String,
    pub settled_on: Option<String>,
    pub notes: String,
}
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, TS)]
#[serde(tag = "kind", content = "fields")]
pub enum Record {
    #[serde(rename = "projects")]
    Project(Option<Project>),
    #[serde(rename = "milestones")]
    Milestone(Option<Milestone>),
    #[serde(rename = "tasks")]
    Task(Option<Task>),
    #[serde(rename = "notes")]
    Note(Option<Note>),
    #[serde(rename = "job_applications")]
    Job(Option<Job>),
    #[serde(rename = "finance_entries")]
    Finance(Option<Finance>),
}
pub type Records = BTreeMap<String, Record>;
impl Record {
    pub fn kind(&self) -> &'static str {
        match self {
            Self::Project(_) => "projects",
            Self::Milestone(_) => "milestones",
            Self::Task(_) => "tasks",
            Self::Note(_) => "notes",
            Self::Job(_) => "job_applications",
            Self::Finance(_) => "finance_entries",
        }
    }
    pub fn deleted(&self) -> bool {
        match self {
            Self::Project(x) => x.is_none(),
            Self::Milestone(x) => x.is_none(),
            Self::Task(x) => x.is_none(),
            Self::Note(x) => x.is_none(),
            Self::Job(x) => x.is_none(),
            Self::Finance(x) => x.is_none(),
        }
    }
    pub fn tombstone(&self) -> Self {
        match self {
            Self::Project(_) => Self::Project(None),
            Self::Milestone(_) => Self::Milestone(None),
            Self::Task(_) => Self::Task(None),
            Self::Note(_) => Self::Note(None),
            Self::Job(_) => Self::Job(None),
            Self::Finance(_) => Self::Finance(None),
        }
    }
}
#[derive(Debug, Clone, Serialize, Deserialize, TS)]
pub struct TaskEdit {
    pub title: String,
    pub start: Option<String>,
    pub end: Option<String>,
    pub project_id: Option<String>,
    pub category: String,
    pub notes: String,
    pub milestone_id: Option<String>,
}
#[derive(Debug, Clone, Serialize, Deserialize, TS)]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
pub enum Mutation {
    SaveProject {
        uid: Option<String>,
        draft: Project,
    },
    SaveMilestone {
        uid: Option<String>,
        draft: Milestone,
    },
    SaveTask {
        uid: Option<String>,
        draft: TaskEdit,
    },
    CompleteTask {
        uid: String,
        completed: bool,
    },
    UndoTask {
        uid: String,
        expected: Task,
        previous: Task,
    },
    ArrangeTask {
        uid: String,
        start: Option<String>,
        end: Option<String>,
    },
    Today {
        uid: String,
        day: String,
        included: bool,
    },
    AddNote {
        title: String,
    },
    SaveJob {
        uid: Option<String>,
        draft: Job,
    },
    SaveFinance {
        uid: Option<String>,
        draft: Finance,
    },
    Settle {
        uid: String,
        day: String,
        #[ts(type = "number")]
        amount_cents: i64,
    },
    Delete {
        uid: String,
    },
}
#[derive(Debug, Clone, Serialize, Deserialize, TS)]
pub struct AppError {
    pub code: String,
    pub message: String,
    pub field: Option<String>,
}
impl AppError {
    pub fn new(code: &str, message: &str) -> Self {
        Self {
            code: code.into(),
            message: message.into(),
            field: None,
        }
    }
    pub fn validation(message: &str) -> Self {
        Self::new("validation", message)
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
        Self::new("storage", "数据库操作失败，请重试；原有内容仍保留。")
    }
}
impl From<std::io::Error> for AppError {
    fn from(_: std::io::Error) -> Self {
        Self::new("io", "文件读取或写入失败，请检查目录权限。")
    }
}
impl From<serde_json::Error> for AppError {
    fn from(_: serde_json::Error) -> Self {
        Self::validation("数据格式不正确或字段不受支持。")
    }
}
pub type Result<T> = std::result::Result<T, AppError>;
#[derive(Debug, Clone, Serialize, Deserialize, TS)]
pub struct Snapshot {
    pub revision: u32,
    pub records: Records,
    pub local_ids: BTreeMap<String, u32>,
}
#[derive(Debug, Clone, Serialize, Deserialize, TS)]
pub struct Segment {
    #[ts(type = "number")]
    pub id: i64,
    pub start: String,
    pub last_seen: String,
    pub end: Option<String>,
    pub seconds: f64,
    pub app: String,
    pub process: String,
    pub title: String,
    pub kind: String,
    pub status: String,
    pub reason: String,
    pub resume_reason: String,
    pub category: String,
}
#[derive(Debug, Clone, Serialize, Deserialize, TS)]
pub struct CaptureStatus {
    pub running: bool,
    pub message: String,
    pub exclusions: String,
}
#[derive(Debug, Clone, Serialize, Deserialize, TS)]
pub struct SyncSettings {
    pub auto_sync: bool,
    pub check_on_start: bool,
}
impl Default for SyncSettings {
    fn default() -> Self {
        Self {
            auto_sync: false,
            check_on_start: true,
        }
    }
}
#[derive(Debug, Clone, Serialize, Deserialize, TS)]
pub struct Conflict {
    pub uid: String,
    pub base: Option<Record>,
    pub local: Record,
    pub remote: Record,
}
#[derive(Debug, Clone, Serialize, Deserialize, TS)]
pub struct SyncStatus {
    pub busy: bool,
    pub pending: u32,
    pub message: String,
    pub synced_at: Option<String>,
    pub conflicts: Vec<Conflict>,
    pub settings: SyncSettings,
    pub has_token: bool,
}

#[test]
fn export_bindings() {
    let directory = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../src/bindings");
    Mutation::export_all_to(&directory).unwrap();
    Snapshot::export_all_to(&directory).unwrap();
    Segment::export_all_to(&directory).unwrap();
    CaptureStatus::export_all_to(&directory).unwrap();
    SyncStatus::export_all_to(&directory).unwrap();
    AppError::export_all_to(&directory).unwrap();
}
