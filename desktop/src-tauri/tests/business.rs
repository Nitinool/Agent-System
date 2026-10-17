use agent_system::{
    model::*,
    rules,
    store::Store,
    sync::{self, SyncService, Transport},
};
use std::collections::BTreeMap;
const AT: &str = "2026-10-17T12:00:00+08:00";
fn project() -> Project {
    Project {
        name: "Demo".into(),
        goal: "持续优化".into(),
        status: "进行中".into(),
        priority: "普通".into(),
        mode: "探索型".into(),
        category: "开发".into(),
    }
}
fn edit(title: &str, project_id: Option<String>, stage: Option<String>) -> TaskEdit {
    let stage = stage.or_else(|| project_id.as_deref().map(rules::ideas_uid));
    TaskEdit {
        title: title.into(),
        start: Some("2026-10-17".into()),
        end: None,
        project_id,
        category: "开发".into(),
        notes: "备注".into(),
        milestone_id: stage,
    }
}
fn add(records: &mut Records, change: Mutation) -> String {
    rules::mutate(records, change, AT).unwrap()
}
fn task(records: &Records, id: &str) -> Task {
    match &records[id] {
        Record::Task(Some(t)) => t.as_ref().clone(),
        _ => panic!("not a task"),
    }
}
fn finance(status: &str) -> Finance {
    Finance {
        direction: "收入".into(),
        amount_cents: 12850,
        occurred_on: "2026-09-28".into(),
        title: "副业".into(),
        category: "副业收入".into(),
        side_source: "接单".into(),
        status: status.into(),
        settled_on: None,
        notes: String::new(),
    }
}
fn job() -> Job {
    Job {
        company: "公司".into(),
        title: "开发".into(),
        applied_on: "2026-10-17".into(),
        status: "已投递".into(),
        url: "https://example.com/job".into(),
        notes: String::new(),
        interview_at: String::new(),
        written_at: String::new(),
        rejected_at: String::new(),
    }
}

#[test]
fn single_day_future_and_completion_membership() {
    let mut r = Records::new();
    let id = add(
        &mut r,
        Mutation::SaveTask {
            uid: None,
            draft: edit("任务", None, None),
        },
    );
    let t = task(&r, &id);
    assert_eq!(t.range_start, t.range_end);
    assert!(rules::on_day(&t, "2026-10-17"));
    assert!(!rules::on_day(&t, "2026-10-16"));
    add(
        &mut r,
        Mutation::CompleteTask {
            uid: id.clone(),
            completed: true,
        },
    );
    assert!(!rules::on_day(&task(&r, &id), "2026-10-17"));
    assert!(rules::calendar_day(&task(&r, &id), "2026-10-17"));
}
#[test]
fn task_edit_preserves_skips_memberships_hidden_fields_and_stage() {
    let mut r = Records::new();
    let p = add(
        &mut r,
        Mutation::SaveProject {
            uid: None,
            draft: project(),
        },
    );
    let m = add(
        &mut r,
        Mutation::SaveMilestone {
            uid: None,
            draft: Milestone {
                stage_kind: StageKind::Standard,
                project_id: p.clone(),
                name: "第一阶段".into(),
                acceptance: "旧验收字段".into(),
                position: 1,
                completed_at: None,
            },
        },
    );
    let id = add(
        &mut r,
        Mutation::SaveTask {
            uid: None,
            draft: edit("A", Some(p.clone()), Some(m.clone())),
        },
    );
    if let Record::Task(Some(t)) = r.get_mut(&id).unwrap() {
        t.priority = "高".into();
        t.kind = "问题".into();
        t.acceptance = "旧字段".into();
    }
    add(
        &mut r,
        Mutation::Today {
            uid: id.clone(),
            day: "2026-10-17".into(),
            included: false,
        },
    );
    add(
        &mut r,
        Mutation::Today {
            uid: id.clone(),
            day: "2026-10-21".into(),
            included: true,
        },
    );
    add(
        &mut r,
        Mutation::SaveTask {
            uid: Some(id.clone()),
            draft: edit("重命名", Some(p), Some(m.clone())),
        },
    );
    let t = task(&r, &id);
    assert_eq!(t.milestone_id, Some(m));
    assert_eq!(t.priority, "高");
    assert_eq!(t.acceptance, "旧字段");
    assert!(!rules::on_day(&t, "2026-10-17"));
    assert!(rules::on_day(&t, "2026-10-21"));
    let mut p2 = project();
    p2.name = "另一个项目".into();
    let p2 = add(
        &mut r,
        Mutation::SaveProject {
            uid: None,
            draft: p2,
        },
    );
    add(
        &mut r,
        Mutation::SaveTask {
            uid: Some(id.clone()),
            draft: edit("换项目", Some(p2), None),
        },
    );
    assert_eq!(
        task(&r, &id).milestone_id,
        task(&r, &id).project_id.as_deref().map(rules::ideas_uid)
    );
}
#[test]
fn completion_history_is_real_repeat_safe_and_survives_undo() {
    let mut r = Records::new();
    let id = add(
        &mut r,
        Mutation::SaveTask {
            uid: None,
            draft: edit("A", None, None),
        },
    );
    let previous = task(&r, &id);
    add(
        &mut r,
        Mutation::CompleteTask {
            uid: id.clone(),
            completed: true,
        },
    );
    let expected = task(&r, &id);
    add(
        &mut r,
        Mutation::CompleteTask {
            uid: id.clone(),
            completed: true,
        },
    );
    assert_eq!(task(&r, &id).completions.len(), 1);
    add(
        &mut r,
        Mutation::UndoTask {
            uid: id.clone(),
            expected: Box::new(expected),
            previous: Box::new(previous),
        },
    );
    assert_eq!(task(&r, &id).completions.len(), 1);
    assert!(task(&r, &id).completions[0].reopened_at.is_some());
    add(
        &mut r,
        Mutation::CompleteTask {
            uid: id.clone(),
            completed: true,
        },
    );
    assert_eq!(task(&r, &id).completions.len(), 2);
}
#[test]
fn stale_undo_rejected() {
    let mut r = Records::new();
    let id = add(
        &mut r,
        Mutation::SaveTask {
            uid: None,
            draft: edit("A", None, None),
        },
    );
    let previous = task(&r, &id);
    add(
        &mut r,
        Mutation::CompleteTask {
            uid: id.clone(),
            completed: true,
        },
    );
    let expected = task(&r, &id);
    add(
        &mut r,
        Mutation::SaveTask {
            uid: Some(id.clone()),
            draft: edit("B", None, None),
        },
    );
    assert!(rules::mutate(
        &mut r,
        Mutation::UndoTask {
            uid: id,
            expected: Box::new(expected),
            previous: Box::new(previous)
        },
        AT
    )
    .is_err());
}
#[test]
fn stage_invalidated_on_reopen_and_empty_stage() {
    let mut r = Records::new();
    let p = add(
        &mut r,
        Mutation::SaveProject {
            uid: None,
            draft: project(),
        },
    );
    let m = add(
        &mut r,
        Mutation::SaveMilestone {
            uid: None,
            draft: Milestone {
                stage_kind: StageKind::Standard,
                project_id: p.clone(),
                name: "阶段".into(),
                acceptance: String::new(),
                position: 1,
                completed_at: None,
            },
        },
    );
    let t = add(
        &mut r,
        Mutation::SaveTask {
            uid: None,
            draft: edit("A", Some(p), Some(m.clone())),
        },
    );
    add(
        &mut r,
        Mutation::CompleteTask {
            uid: t.clone(),
            completed: true,
        },
    );
    if let Record::Milestone(Some(m)) = r.get_mut(&m).unwrap() {
        m.completed_at = Some(AT.into())
    }
    rules::validate(&r).unwrap();
    add(
        &mut r,
        Mutation::CompleteTask {
            uid: t,
            completed: false,
        },
    );
    assert!(matches!(&r[&m],Record::Milestone(Some(m)) if m.completed_at.is_none()));
}
#[test]
fn range_changes_clear_exclusions_but_noop_save_keeps_them() {
    let mut r = Records::new();
    let id = add(
        &mut r,
        Mutation::SaveTask {
            uid: None,
            draft: edit("A", None, None),
        },
    );
    add(
        &mut r,
        Mutation::Today {
            uid: id.clone(),
            day: "2026-10-17".into(),
            included: false,
        },
    );
    add(
        &mut r,
        Mutation::ArrangeTask {
            uid: id.clone(),
            start: Some("2026-10-18".into()),
            end: Some("2026-10-24".into()),
        },
    );
    assert!(task(&r, &id).excluded_days.is_empty());
    assert!(rules::on_day(&task(&r, &id), "2026-10-22"));
    assert!(!rules::on_day(&task(&r, &id), "2026-10-25"));
}
#[test]
fn invalid_range_has_no_partial_database_write() {
    let dir = tempfile::tempdir().unwrap();
    let mut s = Store::open(&dir.path().join("test.sqlite3")).unwrap();
    let mut draft = edit("A", None, None);
    draft.start = Some("2026-10-20".into());
    draft.end = Some("2026-10-19".into());
    assert!(s
        .mutate(Mutation::SaveTask { uid: None, draft }, 0)
        .is_err());
    assert!(s.snapshot().unwrap().records.is_empty());
    assert_eq!(s.revision().unwrap(), 0);
}
#[test]
fn finance_pending_and_settlement_keep_original_entry_and_date() {
    let mut r = Records::new();
    let id = add(
        &mut r,
        Mutation::SaveFinance {
            uid: None,
            draft: finance("待结算"),
        },
    );
    add(
        &mut r,
        Mutation::Settle {
            uid: id.clone(),
            day: "2026-10-02".into(),
            amount_cents: 12000,
        },
    );
    assert_eq!(r.len(), 1);
    assert!(
        matches!(&r[&id],Record::Finance(Some(f)) if f.occurred_on=="2026-09-28"&&f.settled_on.as_deref()==Some("2026-10-02")&&f.amount_cents==12000)
    );
    assert!(rules::mutate(
        &mut r,
        Mutation::Settle {
            uid: id,
            day: "2026-10-03".into(),
            amount_cents: 12000
        },
        AT
    )
    .is_err());
}
#[test]
fn finance_rejects_fractional_cents_invalid_status_and_reverse_dates() {
    let mut r = Records::new();
    let mut f = finance("待结算");
    f.side_source.clear();
    assert!(rules::mutate(
        &mut r,
        Mutation::SaveFinance {
            uid: None,
            draft: f
        },
        AT
    )
    .is_err());
    let mut f = finance("已到账");
    f.settled_on = Some("2026-09-27".into());
    assert!(rules::mutate(
        &mut Records::new(),
        Mutation::SaveFinance {
            uid: None,
            draft: f
        },
        AT
    )
    .is_err());
}
#[test]
fn recruitment_priority_clear_and_manual_offer() {
    let mut r = Records::new();
    let id = add(
        &mut r,
        Mutation::SaveJob {
            uid: None,
            draft: job(),
        },
    );
    let mut j = job();
    j.written_at = "2026-10-18".into();
    j.interview_at = "2026-10-19T13:00:00".into();
    add(
        &mut r,
        Mutation::SaveJob {
            uid: Some(id.clone()),
            draft: j.clone(),
        },
    );
    assert!(
        matches!(&r[&id],Record::Job(Some(j)) if j.status=="面试中"&&j.interview_at=="2026-10-19 13:00")
    );
    j.status = "面试中".into();
    j.interview_at.clear();
    add(
        &mut r,
        Mutation::SaveJob {
            uid: Some(id.clone()),
            draft: j.clone(),
        },
    );
    assert!(matches!(&r[&id],Record::Job(Some(j)) if j.status=="笔试中"));
    j.status = "已获 Offer".into();
    add(
        &mut r,
        Mutation::SaveJob {
            uid: Some(id.clone()),
            draft: j.clone(),
        },
    );
    assert!(matches!(&r[&id],Record::Job(Some(j)) if j.status=="已获 Offer"));
    j.rejected_at = "2026-10-20".into();
    add(
        &mut r,
        Mutation::SaveJob {
            uid: Some(id.clone()),
            draft: j,
        },
    );
    assert!(matches!(&r[&id],Record::Job(Some(j)) if j.status=="已拒绝"));
}
#[test]
fn recruitment_empty_times_preserves_old_manual_state() {
    let mut r = Records::new();
    let mut j = job();
    j.status = "面试中".into();
    let id = add(
        &mut r,
        Mutation::SaveJob {
            uid: None,
            draft: j.clone(),
        },
    );
    add(
        &mut r,
        Mutation::SaveJob {
            uid: Some(id.clone()),
            draft: j,
        },
    );
    assert!(matches!(&r[&id],Record::Job(Some(j)) if j.status=="面试中"));
}
#[test]
fn stage_time_rejects_timezone_invalid_date_and_retains_seconds() {
    for invalid in [
        "2026-02-30",
        "2026-10-17 24:30",
        "2026-10-17T12:00+08:00",
        "2026-10-17 1:00",
    ] {
        assert!(rules::stage_time(invalid).is_err(), "{invalid}")
    }
    assert_eq!(
        rules::stage_time("2026-10-17T12:00:12").unwrap(),
        "2026-10-17 12:00:12"
    );
}
#[test]
fn note_validation_time_and_restart() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("test.sqlite3");
    {
        let mut s = Store::open(&path).unwrap();
        for text in [" ".into(), "字".repeat(501)] {
            assert!(s.mutate(Mutation::AddNote { title: text }, 0).is_err())
        }
        s.mutate(
            Mutation::AddNote {
                title: "随笔".into(),
            },
            0,
        )
        .unwrap();
    }
    let s = Store::open(&path).unwrap();
    let snap = s.snapshot().unwrap();
    assert_eq!(snap.records.len(), 1);
    assert!(
        matches!(snap.records.values().next().unwrap(),Record::Note(Some(n)) if chrono::DateTime::parse_from_rfc3339(&n.created_at).is_ok())
    );
}
#[test]
fn note_all_history_syncs_beyond_display_limit() {
    let mut r = Records::new();
    for i in 0..205 {
        add(
            &mut r,
            Mutation::AddNote {
                title: format!("随笔{i}"),
            },
        );
    }
    let text = sync::encode(&r).unwrap();
    assert_eq!(sync::decode(&text).unwrap().len(), 205);
}
#[test]
fn project_delete_retains_tasks_and_completion_history() {
    let mut r = Records::new();
    let p = add(
        &mut r,
        Mutation::SaveProject {
            uid: None,
            draft: project(),
        },
    );
    let id = add(
        &mut r,
        Mutation::SaveTask {
            uid: None,
            draft: edit("A", Some(p.clone()), None),
        },
    );
    add(
        &mut r,
        Mutation::CompleteTask {
            uid: id.clone(),
            completed: true,
        },
    );
    add(&mut r, Mutation::Delete { uid: p.clone() });
    let t = task(&r, &id);
    assert_eq!(t.project_id, None);
    assert_eq!(t.completions.len(), 1);
    assert_eq!(t.completions[0].project_id, None);
    assert!(r[&p].deleted());
}
#[test]
fn same_name_projects_rejected() {
    let mut r = Records::new();
    add(
        &mut r,
        Mutation::SaveProject {
            uid: None,
            draft: project(),
        },
    );
    let mut p = project();
    p.name = "demo".into();
    assert!(rules::mutate(
        &mut r,
        Mutation::SaveProject {
            uid: None,
            draft: p
        },
        AT
    )
    .is_err());
}
#[test]
fn stale_revision_and_sql_failure_do_not_partial_commit() {
    let d = tempfile::tempdir().unwrap();
    let mut s = Store::open(&d.path().join("test.sqlite3")).unwrap();
    s.mutate(Mutation::AddNote { title: "A".into() }, 0)
        .unwrap();
    assert!(s
        .mutate(Mutation::AddNote { title: "B".into() }, 0)
        .is_err());
    s.db.execute_batch("CREATE TRIGGER fail_insert BEFORE INSERT ON records BEGIN SELECT RAISE(ABORT,'failure'); END;").unwrap();
    assert!(s
        .mutate(Mutation::AddNote { title: "B".into() }, 1)
        .is_err());
    assert_eq!(s.snapshot().unwrap().records.len(), 1);
    assert_eq!(s.revision().unwrap(), 1);
}
#[test]
fn wire_versions_and_tombstone_select_version() {
    let mut r = Records::new();
    assert_eq!(
        serde_json::from_str::<serde_json::Value>(&sync::encode(&r).unwrap()).unwrap()["version"],
        1
    );
    let id = add(
        &mut r,
        Mutation::SaveJob {
            uid: None,
            draft: job(),
        },
    );
    add(&mut r, Mutation::Delete { uid: id });
    let text = sync::encode(&r).unwrap();
    assert!(text.contains("\"version\": 5"));
    assert_eq!(sync::decode(&text).unwrap(), r);
}
#[test]
fn malformed_wire_duplicate_keys_unknown_fields_and_old_note_rejected() {
    for s in [
        "{\"format\":\"agent-system-data\",\"version\":1,\"version\":2,\"records\":{}}",
        "{\"format\":\"agent-system-data\",\"version\":true,\"records\":{}}",
        "{\"format\":\"agent-system-data\",\"version\":1,\"records\":{},\"extra\":1}",
    ] {
        assert!(sync::decode(s).is_err())
    }
    let mut r = Records::new();
    add(&mut r, Mutation::AddNote { title: "A".into() });
    let text = sync::encode(&r)
        .unwrap()
        .replace("\"version\": 4", "\"version\": 3");
    assert!(sync::decode(&text).is_err());
}
#[test]
fn old_job_wire_upgrades_without_false_changes() {
    let id = "a".repeat(32);
    let payload = serde_json::json!({"format":"agent-system-data","version":1,"records":{id:{"kind":"job_applications","fields":{"company":"公司","title":"岗位","applied_on":"2026-10-17","status":"面试中","url":"","notes":""}}}});
    let r = sync::decode(&payload.to_string()).unwrap();
    let (merged, conflicts) = sync::merge(&r, &r, &r, &BTreeMap::new()).unwrap();
    assert!(conflicts.is_empty());
    assert_eq!(merged, r);
}
#[test]
fn independent_adds_merge_and_conflict_choice_is_record_level() {
    let mut local = Records::new();
    add(
        &mut local,
        Mutation::AddNote {
            title: "本机".into(),
        },
    );
    let mut remote = Records::new();
    add(
        &mut remote,
        Mutation::AddNote {
            title: "远端".into(),
        },
    );
    let (r, c) = sync::merge(&Records::new(), &local, &remote, &BTreeMap::new()).unwrap();
    assert_eq!(r.len(), 2);
    assert!(c.is_empty());
    let base = r.clone();
    let uid = local.keys().next().unwrap().clone();
    let mut local = base.clone();
    let mut remote = base.clone();
    if let Record::Note(Some(n)) = local.get_mut(&uid).unwrap() {
        n.title = "修改1".into()
    }
    if let Record::Note(Some(n)) = remote.get_mut(&uid).unwrap() {
        n.title = "修改2".into()
    }
    let (_, c) = sync::merge(&base, &local, &remote, &BTreeMap::new()).unwrap();
    assert_eq!(c.len(), 1);
    let (r, c) = sync::merge(
        &base,
        &local,
        &remote,
        &BTreeMap::from([(uid.clone(), "remote".into())]),
    )
    .unwrap();
    assert!(c.is_empty());
    assert_eq!(r[&uid], remote[&uid]);
}
#[test]
fn missing_shared_record_refuses_sync() {
    let mut base = Records::new();
    add(&mut base, Mutation::AddNote { title: "A".into() });
    assert!(sync::merge(&base, &base, &Records::new(), &BTreeMap::new()).is_err());
}
#[test]
fn import_backup_and_rollback_preserve_baseline() {
    let d = tempfile::tempdir().unwrap();
    let mut s = Store::open(&d.path().join("test.sqlite3")).unwrap();
    let mut r = Records::new();
    add(
        &mut r,
        Mutation::AddNote {
            title: "远端".into(),
        },
    );
    s.import(&Records::new(), &r).unwrap();
    assert_eq!(s.baseline().unwrap(), r);
    assert_eq!(
        std::fs::read_dir(d.path().join("backups")).unwrap().count(),
        1
    );
    let before = s.snapshot().unwrap();
    s.db.execute_batch("CREATE TRIGGER fail_insert BEFORE INSERT ON records BEGIN SELECT RAISE(ABORT,'failure'); END;").unwrap();
    let mut next = r.clone();
    add(
        &mut next,
        Mutation::AddNote {
            title: "另一条".into(),
        },
    );
    assert!(s.import(&r, &next).is_err());
    assert_eq!(s.snapshot().unwrap().records, before.records);
    assert_eq!(s.baseline().unwrap(), r);
}

struct Fake {
    records: Records,
    publishes: u32,
    fail: bool,
    during_publish: Option<Box<dyn FnMut() + Send>>,
}
impl Transport for Fake {
    fn fetch(&mut self) -> Result<(Records, Option<String>)> {
        if self.fail {
            return Err(AppError::new("network", "测试离线"));
        }
        Ok((self.records.clone(), Some("a".repeat(40))))
    }
    fn publish(&mut self, r: &Records, _: Option<&str>) -> Result<()> {
        self.publishes += 1;
        self.records = r.clone();
        if let Some(f) = &mut self.during_publish {
            f();
        }
        Ok(())
    }
}
#[test]
fn sync_readonly_check_manual_import_and_upload() {
    let d = tempfile::tempdir().unwrap();
    let db = agent_system::store::Database::start(d.path().join("test.sqlite3")).unwrap();
    let service = SyncService::new(db.clone(), d.path().into()).unwrap();
    let mut remote = Records::new();
    add(
        &mut remote,
        Mutation::AddNote {
            title: "远端随笔".into(),
        },
    );
    let mut fake = Fake {
        records: remote.clone(),
        publishes: 0,
        fail: false,
        during_publish: None,
    };
    service
        .execute(&mut fake, true, true, BTreeMap::new())
        .unwrap();
    assert!(db.call(|s| s.snapshot()).unwrap().records.is_empty());
    service
        .execute(&mut fake, false, false, BTreeMap::new())
        .unwrap();
    assert_eq!(db.call(|s| s.snapshot()).unwrap().records, remote);
    assert_eq!(fake.publishes, 0);
    db.call(|s| {
        s.mutate(
            Mutation::AddNote {
                title: "本机".into(),
            },
            1,
        )
    })
    .unwrap();
    service
        .execute(&mut fake, false, false, BTreeMap::new())
        .unwrap();
    assert_eq!(fake.records.len(), 2);
    assert_eq!(fake.publishes, 1);
    drop(service);
    drop(db);
    std::thread::sleep(std::time::Duration::from_millis(30));
}
#[test]
fn upload_during_local_edit_does_not_overwrite_or_advance_baseline() {
    let d = tempfile::tempdir().unwrap();
    let db = agent_system::store::Database::start(d.path().join("test.sqlite3")).unwrap();
    let service = SyncService::new(db.clone(), d.path().into()).unwrap();
    db.call(|s| {
        s.mutate(
            Mutation::AddNote {
                title: "本机".into(),
            },
            0,
        )
    })
    .unwrap();
    let edit_db = db.clone();
    let mut fake = Fake {
        records: Records::new(),
        publishes: 0,
        fail: false,
        during_publish: Some(Box::new(move || {
            edit_db
                .call(|s| {
                    s.mutate(
                        Mutation::AddNote {
                            title: "上传时保存".into(),
                        },
                        1,
                    )
                })
                .unwrap();
        })),
    };
    assert!(service
        .execute(&mut fake, false, false, BTreeMap::new())
        .is_err());
    assert_eq!(db.call(|s| s.snapshot()).unwrap().records.len(), 2);
    assert!(db.call(|s| s.baseline()).unwrap().is_empty());
    drop(fake);
    drop(service);
    drop(db);
    std::thread::sleep(std::time::Duration::from_millis(30));
}
#[test]
fn token_dpapi_roundtrip_and_clear() {
    let d = tempfile::tempdir().unwrap();
    let path = d.path().join("token.dpapi");
    agent_system::platform::save_token(&path, "fake-test-token").unwrap();
    let bytes = std::fs::read(&path).unwrap();
    assert!(!bytes.windows(15).any(|w| w == b"fake-test-token"));
    assert_eq!(
        agent_system::platform::load_token(&path).unwrap(),
        "fake-test-token"
    );
    agent_system::platform::save_token(&path, "").unwrap();
    assert!(!path.exists());
}
#[test]
fn v2_sync_path_is_separate() {
    assert_eq!(sync::REMOTE_PATH, "sync/v2/records.json");
    assert_ne!(sync::REMOTE_PATH, "sync/records.json");
}

#[test]
fn two_isolated_databases_roundtrip_all_types_history_settlement_and_deletion() {
    use agent_system::store::Database;
    fn apply(db: &Database, m: Mutation) -> Snapshot {
        db.call(move |s| {
            let revision = s.revision()?;
            s.mutate(m, revision)
        })
        .unwrap()
    }
    let a = tempfile::tempdir().unwrap();
    let b = tempfile::tempdir().unwrap();
    let adb = Database::start(a.path().join("a.sqlite3")).unwrap();
    let bdb = Database::start(b.path().join("b.sqlite3")).unwrap();
    let aservice = SyncService::new(adb.clone(), a.path().into()).unwrap();
    let bservice = SyncService::new(bdb.clone(), b.path().into()).unwrap();
    let snap = apply(
        &adb,
        Mutation::SaveProject {
            uid: None,
            draft: project(),
        },
    );
    let pid = snap
        .records
        .iter()
        .find(|(_, r)| matches!(r, Record::Project(Some(_))))
        .unwrap()
        .0
        .clone();
    let snap = apply(
        &adb,
        Mutation::SaveMilestone {
            uid: None,
            draft: Milestone {
                stage_kind: StageKind::Standard,
                project_id: pid.clone(),
                name: "阶段".into(),
                acceptance: String::new(),
                position: 1,
                completed_at: None,
            },
        },
    );
    let mid = snap
        .records
        .iter()
        .find(
            |(_, r)| matches!(r,Record::Milestone(Some(m)) if m.stage_kind == StageKind::Standard),
        )
        .unwrap()
        .0
        .clone();
    let snap = apply(
        &adb,
        Mutation::SaveTask {
            uid: None,
            draft: edit("共享事项", Some(pid.clone()), Some(mid.clone())),
        },
    );
    let tid = snap
        .records
        .iter()
        .find(|(_, r)| r.kind() == "tasks")
        .unwrap()
        .0
        .clone();
    apply(
        &adb,
        Mutation::CompleteTask {
            uid: tid.clone(),
            completed: true,
        },
    );
    let mut j = job();
    j.interview_at = "2026-10-20 13:00".into();
    apply(
        &adb,
        Mutation::SaveJob {
            uid: None,
            draft: j,
        },
    );
    let snap = apply(
        &adb,
        Mutation::SaveFinance {
            uid: None,
            draft: finance("待结算"),
        },
    );
    let fid = snap
        .records
        .iter()
        .find(|(_, r)| r.kind() == "finance_entries")
        .unwrap()
        .0
        .clone();
    apply(
        &adb,
        Mutation::AddNote {
            title: "A 随笔".into(),
        },
    );
    let mut remote = Fake {
        records: Records::new(),
        publishes: 0,
        fail: false,
        during_publish: None,
    };
    aservice
        .execute(&mut remote, false, false, BTreeMap::new())
        .unwrap();
    bservice
        .execute(&mut remote, false, false, BTreeMap::new())
        .unwrap();
    assert_eq!(
        adb.call(|s| s.snapshot()).unwrap().records,
        bdb.call(|s| s.snapshot()).unwrap().records
    );
    apply(
        &bdb,
        Mutation::CompleteTask {
            uid: tid.clone(),
            completed: false,
        },
    );
    apply(
        &bdb,
        Mutation::Settle {
            uid: fid.clone(),
            day: "2026-10-17".into(),
            amount_cents: 12000,
        },
    );
    apply(
        &bdb,
        Mutation::AddNote {
            title: "B 随笔".into(),
        },
    );
    apply(
        &adb,
        Mutation::AddNote {
            title: "A 独立新增".into(),
        },
    );
    bservice
        .execute(&mut remote, false, false, BTreeMap::new())
        .unwrap();
    aservice
        .execute(&mut remote, false, false, BTreeMap::new())
        .unwrap();
    bservice
        .execute(&mut remote, false, false, BTreeMap::new())
        .unwrap();
    let current = adb.call(|s| s.snapshot()).unwrap().records;
    assert_eq!(current, bdb.call(|s| s.snapshot()).unwrap().records);
    assert_eq!(task(&current, &tid).milestone_id, Some(mid));
    assert_eq!(task(&current, &tid).completions.len(), 1);
    assert!(task(&current, &tid).completions[0].reopened_at.is_some());
    assert!(
        matches!(&current[&fid],Record::Finance(Some(f))if f.status=="已到账"&&f.amount_cents==12000)
    );
    apply(&adb, Mutation::Delete { uid: pid });
    aservice
        .execute(&mut remote, false, false, BTreeMap::new())
        .unwrap();
    bservice
        .execute(&mut remote, false, false, BTreeMap::new())
        .unwrap();
    let current = bdb.call(|s| s.snapshot()).unwrap().records;
    assert_eq!(task(&current, &tid).project_id, None);
    assert_eq!(task(&current, &tid).completions.len(), 1);
    assert_eq!(task(&current, &tid).completions[0].project_id, None);
    drop(aservice);
    drop(bservice);
    drop(adb);
    drop(bdb);
    std::thread::sleep(std::time::Duration::from_millis(50));
}

#[test]
fn external_connection_changes_invalidate_revision_and_stale_edit() {
    let d = tempfile::tempdir().unwrap();
    let path = d.path().join("test.sqlite3");
    let mut s = Store::open(&path).unwrap();
    let snap = s
        .mutate(Mutation::AddNote { title: "A".into() }, 0)
        .unwrap();
    let uid = snap.records.keys().next().unwrap();
    let other = rusqlite::Connection::open(&path).unwrap();
    let changed = serde_json::to_string(&Record::Note(Some(Note {
        title: "外部保存".into(),
        created_at: AT.into(),
    })))
    .unwrap();
    other
        .execute(
            "UPDATE records SET payload=? WHERE uid=?",
            rusqlite::params![changed, uid],
        )
        .unwrap();
    assert!(s.revision().unwrap() > snap.revision);
    assert!(s
        .mutate(Mutation::AddNote { title: "B".into() }, snap.revision)
        .is_err());
    assert!(
        matches!(s.snapshot().unwrap().records.values().next().unwrap(),Record::Note(Some(n))if n.title=="外部保存")
    );
}
#[test]
fn unsupported_database_is_not_migrated_or_cleared() {
    let d = tempfile::tempdir().unwrap();
    let path = d.path().join("old.sqlite3");
    {
        let db = rusqlite::Connection::open(&path).unwrap();
        db.execute_batch(
            "CREATE TABLE old(value TEXT);INSERT INTO old VALUES('keep');PRAGMA user_version=9;",
        )
        .unwrap();
    }
    assert!(Store::open(&path).is_err());
    let db = rusqlite::Connection::open(path).unwrap();
    assert_eq!(
        db.query_row("PRAGMA user_version", [], |r| r.get::<_, u32>(0))
            .unwrap(),
        9
    );
    assert_eq!(
        db.query_row("SELECT value FROM old", [], |r| r.get::<_, String>(0))
            .unwrap(),
        "keep"
    );
}
#[test]
fn corrupt_preferences_and_token_do_not_disable_business_storage() {
    let d = tempfile::tempdir().unwrap();
    std::fs::write(d.path().join("sync-settings.json"), "{bad").unwrap();
    std::fs::write(d.path().join("sync-token.dpapi"), "not encrypted").unwrap();
    let db = agent_system::store::Database::start(d.path().join("test.sqlite3")).unwrap();
    let service = SyncService::new(db.clone(), d.path().into()).unwrap();
    let status = service.status().unwrap();
    assert!(!status.settings.auto_sync);
    assert!(!status.settings.check_on_start);
    assert!(!status.has_token);
    db.call(|s| {
        s.mutate(
            Mutation::AddNote {
                title: "仍可保存".into(),
            },
            0,
        )
    })
    .unwrap();
    drop(service);
    drop(db);
    std::thread::sleep(std::time::Duration::from_millis(30));
}
#[test]
fn invalid_token_does_not_persist_new_preferences() {
    let d = tempfile::tempdir().unwrap();
    let db = agent_system::store::Database::start(d.path().join("test.sqlite3")).unwrap();
    let service = SyncService::new(db.clone(), d.path().into()).unwrap();
    assert!(service
        .configure(
            SyncSettings {
                auto_sync: true,
                check_on_start: true
            },
            Some("bad token".into()),
            true,
            false
        )
        .is_err());
    assert!(!d.path().join("sync-settings.json").exists());
    assert!(!service.status().unwrap().settings.auto_sync);
    drop(service);
    drop(db);
    std::thread::sleep(std::time::Duration::from_millis(30));
}
#[test]
fn automatic_conflicts_pause_and_cancel_never_writes() {
    let d = tempfile::tempdir().unwrap();
    let db = agent_system::store::Database::start(d.path().join("test.sqlite3")).unwrap();
    let service = SyncService::new(db.clone(), d.path().into()).unwrap();
    let mut base = Records::new();
    let id = add(
        &mut base,
        Mutation::SaveProject {
            uid: None,
            draft: project(),
        },
    );
    let initial = base.clone();
    db.call(move |s| s.import(&Records::new(), &initial))
        .unwrap();
    let id2 = id.clone();
    db.call(move |s| {
        let mut p = project();
        p.goal = "本机修改".into();
        s.mutate(
            Mutation::SaveProject {
                uid: Some(id2),
                draft: p,
            },
            1,
        )
    })
    .unwrap();
    if let Record::Project(Some(p)) = base.get_mut(&id).unwrap() {
        p.goal = "远端修改".into();
    }
    let mut fake = Fake {
        records: base.clone(),
        publishes: 0,
        fail: false,
        during_publish: None,
    };
    let before = db.call(|s| s.snapshot()).unwrap().records;
    service
        .execute(&mut fake, false, true, BTreeMap::new())
        .unwrap();
    assert_eq!(service.status().unwrap().conflicts.len(), 1);
    assert_eq!(fake.publishes, 0);
    service.cancel_conflicts();
    assert!(service.status().unwrap().conflicts.is_empty());
    assert_eq!(db.call(|s| s.snapshot()).unwrap().records, before);
    assert_eq!(fake.records, base);
    drop(service);
    drop(db);
    std::thread::sleep(std::time::Duration::from_millis(30));
}
#[test]
fn offline_failure_preserves_unsynced_data_and_baseline() {
    let d = tempfile::tempdir().unwrap();
    let db = agent_system::store::Database::start(d.path().join("test.sqlite3")).unwrap();
    let service = SyncService::new(db.clone(), d.path().into()).unwrap();
    db.call(|s| {
        s.mutate(
            Mutation::AddNote {
                title: "离线记录".into(),
            },
            0,
        )
    })
    .unwrap();
    let before = db.call(|s| s.snapshot()).unwrap().records;
    let mut fake = Fake {
        records: Records::new(),
        publishes: 0,
        fail: true,
        during_publish: None,
    };
    assert!(service
        .execute(&mut fake, false, true, BTreeMap::new())
        .is_err());
    assert_eq!(db.call(|s| s.snapshot()).unwrap().records, before);
    assert!(db.call(|s| s.baseline()).unwrap().is_empty());
    assert_eq!(fake.publishes, 0);
    drop(service);
    drop(db);
    std::thread::sleep(std::time::Duration::from_millis(30));
}
