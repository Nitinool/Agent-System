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
fn draft(start: Option<&str>, end: Option<&str>) -> Draft {
    Draft {
        title: "  开发事项便签  ".into(),
        start: start.map(Into::into),
        end: end.map(Into::into),
        category: "开发".into(),
        color: "#3b82f6".into(),
        notes: "保留备注".into(),
    }
}
fn add(s: &mut Store, d: Draft) -> Snapshot {
    let revision = s.snapshot().unwrap().revision;
    s.mutate(Mutation::Save { id: None, draft: d }, revision)
        .unwrap()
}
#[test]
fn single_day_range_and_completed_items_keep_date_membership() {
    let temp = temporary();
    let mut s = Store::open(&temp.path().join("tasks.sqlite3")).unwrap();
    let snap = add(&mut s, draft(Some("2026-11-04"), None));
    let t = &snap.tasks[0];
    assert_eq!(t.title, "开发事项便签");
    assert_eq!(t.end, t.start);
    assert!(on_day(t, "2026-11-04"));
    assert!(!on_day(t, "2026-11-05"));
    let snap = s
        .mutate(
            Mutation::Complete {
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
            Mutation::Complete {
                id: id.clone(),
                completed: true,
            },
            snap.revision,
        )
        .unwrap();
    let snap = s
        .mutate(
            Mutation::Complete {
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
            Mutation::Complete {
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
            Mutation::Complete {
                id: id.clone(),
                completed: true,
            },
            first.revision,
        )
        .unwrap();
    assert_eq!(
        s.mutate(
            Mutation::Save {
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
        .mutate(Mutation::Delete { id: id.clone() }, next.revision)
        .unwrap();
    assert!(deleted.tasks.is_empty());
    assert!(s
        .mutate(
            Mutation::Save {
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
        assert!(s.mutate(Mutation::Save { id: None, draft: d }, 0).is_err());
    }
    let mut d = draft(None, None);
    d.title = "  ".into();
    assert!(s.mutate(Mutation::Save { id: None, draft: d }, 0).is_err());
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
            Mutation::Complete {
                id: id.clone(),
                completed: true,
            },
            snap.revision,
        )
        .unwrap();
    let snap = s
        .mutate(
            Mutation::Today {
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
            Mutation::Today {
                id,
                day: "2026-11-04".into(),
                included: true,
            },
            snap.revision,
        )
        .unwrap();
    assert!(on_day(&snap.tasks[0], "2026-11-04"));
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
