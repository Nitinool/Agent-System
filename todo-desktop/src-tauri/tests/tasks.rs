use task_notes::{
    directory::checked_directory,
    model::*,
    store::{on_day, Store},
};

fn temporary() -> tempfile::TempDir {
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("target");
    std::fs::create_dir_all(&root).unwrap();
    tempfile::tempdir_in(root).unwrap()
}

fn draft(start: Option<&str>, end: Option<&str>) -> TaskDraft {
    TaskDraft {
        title: "  开发事项便签  ".into(),
        notes: "保留备注".into(),
        color: "#3b82f6".into(),
        priority: 4,
        start: start.map(Into::into),
        end: end.map(Into::into),
        project_id: None,
        section_id: None,
        parent_id: None,
        label_ids: vec![],
    }
}

fn add(s: &mut Store, d: TaskDraft) -> Snapshot {
    let revision = s.snapshot().unwrap().revision;
    s.mutate(Mutation::TaskSave { id: None, draft: d }, revision)
        .unwrap()
}

fn project(s: &mut Store, name: &str) -> Snapshot {
    let revision = s.snapshot().unwrap().revision;
    s.mutate(
        Mutation::ProjectSave {
            id: None,
            draft: ProjectDraft {
                name: name.into(),
                color: "#3b82f6".into(),
                favorite: false,
            },
        },
        revision,
    )
    .unwrap()
}

#[test]
fn single_day_range_and_completed_items_keep_date_membership() {
    let temp = temporary();
    let mut s = Store::open(&temp.path().join("tasks.sqlite3")).unwrap();
    let snap = add(&mut s, draft(Some("2026-11-04"), None));
    let t = &snap.tasks[0];
    assert_eq!(t.title, "开发事项便签");
    assert_eq!(t.priority, 4);
    assert!(on_day(t, "2026-11-04"));
    assert!(!on_day(t, "2026-11-05"));
    let snap = s
        .mutate(
            Mutation::TaskComplete {
                id: t.id.clone(),
                completed: true,
            },
            snap.revision,
        )
        .unwrap();
    assert!(on_day(&snap.tasks[0], "2026-11-04"));
    assert!(snap.tasks[0].completed);
    let snap = add(&mut s, draft(Some("2026-11-01"), Some("2026-11-07")));
    assert!(on_day(&snap.tasks[1], "2026-11-01"));
    assert!(on_day(&snap.tasks[1], "2026-11-07"));
    assert!(!on_day(&snap.tasks[1], "2026-11-08"));
}

#[test]
fn complete_idempotently_then_reopen_retains_real_history_and_survives_restart() {
    let temp = temporary();
    let path = temp.path().join("tasks.sqlite3");
    let mut s = Store::open(&path).unwrap();
    let snap = add(&mut s, draft(Some("2026-11-04"), None));
    let id = snap.tasks[0].id.clone();
    let snap = s
        .mutate(
            Mutation::TaskComplete {
                id: id.clone(),
                completed: true,
            },
            snap.revision,
        )
        .unwrap();
    let snap = s
        .mutate(
            Mutation::TaskComplete {
                id: id.clone(),
                completed: true,
            },
            snap.revision,
        )
        .unwrap();
    assert_eq!(snap.tasks[0].completions.len(), 1);
    let at = snap.tasks[0].completions[0].completed_at.clone();
    let snap = s
        .mutate(
            Mutation::TaskComplete {
                id,
                completed: false,
            },
            snap.revision,
        )
        .unwrap();
    assert!(!snap.tasks[0].completed);
    assert!(snap.tasks[0].completions[0].reopened_at.is_some());
    assert_eq!(snap.tasks[0].completions[0].completed_at, at);
    drop(s);
    let s = Store::open(&path).unwrap();
    assert_eq!(s.snapshot().unwrap().tasks, snap.tasks);
}

#[test]
fn stale_second_window_cannot_overwrite_first_window_or_deleted_task() {
    let temp = temporary();
    let mut s = Store::open(&temp.path().join("tasks.sqlite3")).unwrap();
    let first = add(&mut s, draft(Some("2026-11-04"), None));
    let id = first.tasks[0].id.clone();
    let next = s
        .mutate(
            Mutation::TaskComplete {
                id: id.clone(),
                completed: true,
            },
            first.revision,
        )
        .unwrap();
    assert_eq!(
        s.mutate(
            Mutation::TaskSave {
                id: Some(id.clone()),
                draft: draft(None, None)
            },
            first.revision
        )
        .unwrap_err()
        .code,
        "stale"
    );
    assert_eq!(s.snapshot().unwrap().tasks, next.tasks);
    let deleted = s
        .mutate(Mutation::TaskDelete { id: id.clone() }, next.revision)
        .unwrap();
    assert!(deleted.tasks.is_empty());
    assert!(s
        .mutate(
            Mutation::TaskSave {
                id: Some(id),
                draft: draft(None, None)
            },
            deleted.revision
        )
        .is_err());
    assert!(s.snapshot().unwrap().tasks.is_empty());
}

#[test]
fn invalid_dates_and_content_roll_back_without_advancing_revision() {
    let temp = temporary();
    let mut s = Store::open(&temp.path().join("tasks.sqlite3")).unwrap();
    for d in [
        draft(None, Some("2026-11-04")),
        draft(Some("2026-02-30"), None),
        draft(Some("2026-11-05"), Some("2026-11-04")),
    ] {
        assert!(s.mutate(Mutation::TaskSave { id: None, draft: d }, 0).is_err());
    }
    let mut d = draft(None, None);
    d.title = "  ".into();
    assert!(s.mutate(Mutation::TaskSave { id: None, draft: d }, 0).is_err());
    let mut d = draft(None, None);
    d.priority = 5;
    assert!(s.mutate(Mutation::TaskSave { id: None, draft: d }, 0).is_err());
    let snap = s.snapshot().unwrap();
    assert_eq!(snap.revision, 0);
    assert!(snap.tasks.is_empty());
}

#[test]
fn remove_only_today_from_range_and_put_back_preserves_other_dates_and_history() {
    let temp = temporary();
    let mut s = Store::open(&temp.path().join("tasks.sqlite3")).unwrap();
    let snap = add(&mut s, draft(Some("2026-11-01"), Some("2026-11-07")));
    let id = snap.tasks[0].id.clone();
    let snap = s
        .mutate(
            Mutation::TaskComplete {
                id: id.clone(),
                completed: true,
            },
            snap.revision,
        )
        .unwrap();
    let snap = s
        .mutate(
            Mutation::TaskToday {
                id: id.clone(),
                day: "2026-11-04".into(),
                included: false,
            },
            snap.revision,
        )
        .unwrap();
    assert!(!on_day(&snap.tasks[0], "2026-11-04"));
    assert!(on_day(&snap.tasks[0], "2026-11-05"));
    assert!(snap.tasks[0].completed);
    assert_eq!(snap.tasks[0].completions.len(), 1);
    let snap = s
        .mutate(
            Mutation::TaskToday {
                id,
                day: "2026-11-04".into(),
                included: true,
            },
            snap.revision,
        )
        .unwrap();
    assert!(on_day(&snap.tasks[0], "2026-11-04"));
    assert!(snap.tasks[0].excluded_days.is_empty());
}

#[test]
fn future_schema_is_rejected_and_physical_isolation_does_not_create_data() {
    let temp = temporary();
    let path = temp.path().join("tasks.sqlite3");
    let c = rusqlite::Connection::open(&path).unwrap();
    c.execute_batch("PRAGMA user_version=99").unwrap();
    drop(c);
    assert!(Store::open(&path).is_err());
    assert_eq!(
        rusqlite::Connection::open(&path)
            .unwrap()
            .query_row("PRAGMA user_version", [], |r| r.get::<_, u32>(0))
            .unwrap(),
        99
    );
    let isolated = temp.path().join("Packages/Host_123/LocalCache/Local");
    std::fs::create_dir_all(&isolated).unwrap();
    assert!(checked_directory(&isolated).is_err());
    assert!(!isolated.join("Task-Notes").exists());
    let normal = checked_directory(temp.path()).unwrap();
    assert_eq!(normal, temp.path().join("Task-Notes"));
    assert!(!normal.exists());
}

#[test]
fn projects_sections_labels_priority_and_subtasks_round_trip() {
    let temp = temporary();
    let mut s = Store::open(&temp.path().join("tasks.sqlite3")).unwrap();
    let snap = project(&mut s, "  工作  ");
    assert_eq!(snap.projects[0].name, "工作");
    let project_id = snap.projects[0].id.clone();
    let snap = s
        .mutate(
            Mutation::SectionSave {
                id: None,
                project_id: project_id.clone(),
                name: "本周".into(),
            },
            snap.revision,
        )
        .unwrap();
    let section_id = snap.sections[0].id.clone();
    let snap = s
        .mutate(
            Mutation::LabelSave {
                id: None,
                draft: LabelDraft {
                    name: "紧急".into(),
                    color: "#db2777".into(),
                },
            },
            snap.revision,
        )
        .unwrap();
    let label_id = snap.labels[0].id.clone();

    let mut parent = draft(Some("2026-11-04"), None);
    parent.title = "写周报".into();
    parent.priority = 1;
    parent.project_id = Some(project_id.clone());
    parent.section_id = Some(section_id.clone());
    parent.label_ids = vec![label_id.clone(), label_id.clone()];
    let snap = s
        .mutate(
            Mutation::TaskSave {
                id: None,
                draft: parent,
            },
            snap.revision,
        )
        .unwrap();
    let parent_id = snap.tasks[0].id.clone();
    assert_eq!(snap.tasks[0].priority, 1);
    assert_eq!(snap.tasks[0].label_ids, vec![label_id.clone()]);
    assert_eq!(snap.tasks[0].section_id.as_deref(), Some(section_id.as_str()));

    // 子事项不带项目时跟随父事项，不会掉进收件箱。
    let mut child = draft(Some("2026-11-04"), None);
    child.title = "收集数据".into();
    child.parent_id = Some(parent_id.clone());
    let snap = s
        .mutate(
            Mutation::TaskSave {
                id: None,
                draft: child,
            },
            snap.revision,
        )
        .unwrap();
    assert_eq!(snap.tasks[1].project_id.as_deref(), Some(project_id.as_str()));
    assert_eq!(snap.tasks[1].parent_id.as_deref(), Some(parent_id.as_str()));

    // 父事项不能成为自己的祖先。
    let mut looped = draft(None, None);
    looped.title = "写周报".into();
    looped.project_id = Some(project_id.clone());
    looped.parent_id = Some(snap.tasks[1].id.clone());
    assert_eq!(
        s.mutate(
            Mutation::TaskSave {
                id: Some(parent_id.clone()),
                draft: looped
            },
            snap.revision
        )
        .unwrap_err()
        .code,
        "validation"
    );

    // 删除标签只解除关联，不删事项。
    let snap = s
        .mutate(Mutation::LabelDelete { id: label_id }, snap.revision)
        .unwrap();
    assert_eq!(snap.tasks.len(), 2);
    assert!(snap.tasks[0].label_ids.is_empty());
}

#[test]
fn deleting_projects_and_sections_is_blocked_while_tasks_remain() {
    let temp = temporary();
    let mut s = Store::open(&temp.path().join("tasks.sqlite3")).unwrap();
    let snap = project(&mut s, "工作");
    let project_id = snap.projects[0].id.clone();
    let snap = s
        .mutate(
            Mutation::SectionSave {
                id: None,
                project_id: project_id.clone(),
                name: "本周".into(),
            },
            snap.revision,
        )
        .unwrap();
    let section_id = snap.sections[0].id.clone();
    let mut d = draft(Some("2026-11-04"), None);
    d.project_id = Some(project_id.clone());
    d.section_id = Some(section_id.clone());
    let snap = s
        .mutate(Mutation::TaskSave { id: None, draft: d }, snap.revision)
        .unwrap();
    let task_id = snap.tasks[0].id.clone();

    for mutation in [
        Mutation::ProjectDelete {
            id: project_id.clone(),
        },
        Mutation::SectionDelete {
            id: section_id.clone(),
        },
    ] {
        let error = s.mutate(mutation, snap.revision).unwrap_err();
        assert_eq!(error.code, "validation");
    }

    // 移到收件箱后两者都能删，事项本身保留。
    let snap = s
        .mutate(
            Mutation::TaskMove {
                id: task_id,
                project_id: None,
                section_id: None,
                parent_id: None,
            },
            snap.revision,
        )
        .unwrap();
    assert_eq!(snap.tasks[0].project_id, None);
    let revision = s
        .mutate(Mutation::SectionDelete { id: section_id }, snap.revision)
        .unwrap()
        .revision;
    let snap = s
        .mutate(Mutation::ProjectDelete { id: project_id }, revision)
        .unwrap();
    assert!(snap.projects.is_empty());
    assert_eq!(snap.tasks.len(), 1);
}

#[test]
fn deleting_a_parent_removes_its_subtasks_only() {
    let temp = temporary();
    let mut s = Store::open(&temp.path().join("tasks.sqlite3")).unwrap();
    let snap = add(&mut s, draft(None, None));
    let parent_id = snap.tasks[0].id.clone();
    let mut child = draft(None, None);
    child.title = "子任务".into();
    child.parent_id = Some(parent_id.clone());
    s.mutate(
        Mutation::TaskSave {
            id: None,
            draft: child,
        },
        snap.revision,
    )
    .unwrap();
    let snap = add(&mut s, {
        let mut other = draft(None, None);
        other.title = "另一条".into();
        other
    });
    assert_eq!(snap.tasks.len(), 3);
    let snap = s
        .mutate(Mutation::TaskDelete { id: parent_id }, snap.revision)
        .unwrap();
    assert_eq!(snap.tasks.len(), 1);
    assert!(snap.tasks.iter().all(|t| t.parent_id.is_none()));
}

#[test]
fn reorder_rewrites_positions_used_by_snapshot_order() {
    let temp = temporary();
    let mut s = Store::open(&temp.path().join("tasks.sqlite3")).unwrap();
    add(&mut s, draft(None, None));
    let snap = add(&mut s, draft(None, None));
    let ids: Vec<String> = snap.tasks.iter().map(|t| t.id.clone()).collect();
    let reversed: Vec<String> = ids.iter().rev().cloned().collect();
    let snap = s
        .mutate(
            Mutation::TaskReorder {
                ids: reversed.clone(),
            },
            snap.revision,
        )
        .unwrap();
    assert_eq!(
        snap.tasks.iter().map(|t| t.id.clone()).collect::<Vec<_>>(),
        reversed
    );
}

#[test]
fn upgrading_schema_one_keeps_tasks_days_history_and_backs_up() {
    let temp = temporary();
    let path = temp.path().join("tasks.sqlite3");
    let legacy = rusqlite::Connection::open(&path).unwrap();
    legacy
        .execute_batch(
            "CREATE TABLE tasks(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
             CREATE TABLE state(id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL);
             INSERT INTO state VALUES(1,7);
             PRAGMA user_version=1;",
        )
        .unwrap();
    let payload = serde_json::json!({
        "id": "legacy-1",
        "title": "旧事项",
        "start": "2026-11-01",
        "end": "2026-11-07",
        "category": "开发",
        "color": "#8b5cf6",
        "notes": "旧备注",
        "completed": true,
        "completions": [
            {"completed_at": "2026-11-03T09:00:00+08:00", "reopened_at": null},
            {"completed_at": "2026-11-04T09:00:00+08:00", "reopened_at": "2026-11-04T10:00:00+08:00"}
        ],
        "included_days": ["2026-11-09"],
        "excluded_days": ["2026-11-05"],
        "created_at": "2026-11-01T08:00:00+08:00",
        "updated_at": "2026-11-04T10:00:00+08:00"
    });
    legacy
        .execute(
            "INSERT INTO tasks(id,payload) VALUES(?1,?2)",
            rusqlite::params!["legacy-1", payload.to_string()],
        )
        .unwrap();
    drop(legacy);

    let s = Store::open(&path).unwrap();
    let snap = s.snapshot().unwrap();
    assert_eq!(snap.revision, 7);
    assert_eq!(snap.tasks.len(), 1);
    let task = &snap.tasks[0];
    assert_eq!(task.id, "legacy-1");
    assert_eq!(task.title, "旧事项");
    assert_eq!(task.notes, "旧备注");
    assert_eq!(task.color, "#8b5cf6");
    assert_eq!(task.project_id, None);
    assert_eq!(task.priority, 4);
    assert_eq!(task.created_at, "2026-11-01T08:00:00+08:00");
    assert_eq!(task.completions.len(), 2);
    assert_eq!(task.excluded_days, vec!["2026-11-05".to_string()]);
    assert_eq!(task.included_days, vec!["2026-11-09".to_string()]);
    assert_eq!(snap.labels.len(), 1);
    assert_eq!(snap.labels[0].name, "开发");
    assert_eq!(task.label_ids, vec![snap.labels[0].id.clone()]);
    assert!(!on_day(task, "2026-11-05"));
    assert!(on_day(task, "2026-11-06"));

    let backups: Vec<_> = std::fs::read_dir(temp.path().join("backups"))
        .unwrap()
        .map(|entry| entry.unwrap().path())
        .collect();
    assert_eq!(backups.len(), 1);
    assert!(backups[0].extension().is_some_and(|e| e == "sqlite3"));

    // 再打开一次不应重复迁移，也不应多出备份。
    drop(s);
    let s = Store::open(&path).unwrap();
    assert_eq!(s.snapshot().unwrap().tasks.len(), 1);
    assert_eq!(
        std::fs::read_dir(temp.path().join("backups"))
            .unwrap()
            .count(),
        1
    );
}
