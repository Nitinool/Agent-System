use agent_system::{model::*, rules, store::Store, sync};
use rusqlite::{params, Connection};
use serde_json::{json, Value};
use std::collections::BTreeMap;
const AT: &str = "2026-10-17T12:00:00+08:00";
fn project(name: &str) -> Project {
    Project {
        name: name.into(),
        goal: String::new(),
        status: "进行中".into(),
        priority: "普通".into(),
        mode: "目标型".into(),
        category: "开发".into(),
    }
}
fn apply(r: &mut Records, m: Mutation) -> String {
    rules::mutate(r, m, AT).unwrap()
}
fn add_project(r: &mut Records, name: &str) -> String {
    apply(
        r,
        Mutation::SaveProject {
            uid: None,
            draft: project(name),
        },
    )
}
fn stage(r: &mut Records, p: &str) -> String {
    apply(
        r,
        Mutation::SaveMilestone {
            uid: None,
            draft: Milestone {
                stage_kind: StageKind::Standard,
                project_id: p.into(),
                name: "阶段".into(),
                acceptance: String::new(),
                position: 1,
                completed_at: None,
            },
        },
    )
}
fn edit(p: Option<&str>, s: Option<&str>) -> TaskEdit {
    TaskEdit {
        title: "事项".into(),
        start: Some("2026-10-17".into()),
        end: None,
        project_id: p.map(String::from),
        milestone_id: s.map(String::from),
        category: "学习".into(),
        notes: "保留备注".into(),
    }
}
fn task(r: &Records, id: &str) -> Task {
    match &r[id] {
        Record::Task(Some(t)) => *t.clone(),
        _ => panic!(),
    }
}
fn add_task(r: &mut Records, p: &str, s: &str) -> String {
    apply(
        r,
        Mutation::SaveTask {
            uid: None,
            draft: edit(Some(p), Some(s)),
        },
    )
}

#[test]
fn projects_get_a_unique_deterministic_ideas_stage() {
    let p = "a".repeat(32);
    let mut a = Records::new();
    let mut b = Records::new();
    for r in [&mut a, &mut b] {
        apply(
            r,
            Mutation::SaveProject {
                uid: Some(p.clone()),
                draft: project("项目"),
            },
        );
    }
    assert_eq!(a, b);
    let id = rules::ideas_uid(&p);
    assert!(
        matches!(&a[&id],Record::Milestone(Some(m)) if m.stage_kind==StageKind::Ideas && m.name=="未来想法")
    );
    apply(
        &mut a,
        Mutation::SaveProject {
            uid: Some(p),
            draft: project("改名"),
        },
    );
    assert_eq!(
        a.values()
            .filter(|r| matches!(r, Record::Milestone(Some(_))))
            .count(),
        1
    );
}

#[test]
fn missing_and_foreign_stage_reject_without_database_writes() {
    let d = tempfile::tempdir().unwrap();
    let mut store = Store::open(&d.path().join("a.sqlite3")).unwrap();
    let p = store
        .mutate(
            Mutation::SaveProject {
                uid: None,
                draft: project("A"),
            },
            0,
        )
        .unwrap();
    let pid = p
        .records
        .iter()
        .find(|(_, r)| matches!(r, Record::Project(Some(_))))
        .unwrap()
        .0
        .clone();
    assert!(store
        .mutate(
            Mutation::SaveTask {
                uid: None,
                draft: edit(Some(&pid), None)
            },
            p.revision
        )
        .is_err());
    assert_eq!(store.snapshot().unwrap().records, p.records);
    let mut r = p.records;
    let other = add_project(&mut r, "B");
    let foreign = rules::ideas_uid(&other);
    assert!(rules::mutate(
        &mut r.clone(),
        Mutation::SaveTask {
            uid: None,
            draft: edit(Some(&pid), Some(&foreign))
        },
        AT
    )
    .is_err());
    assert!(rules::mutate(
        &mut r,
        Mutation::SaveTask {
            uid: None,
            draft: edit(None, Some(&foreign))
        },
        AT
    )
    .is_err());
}

#[test]
fn moving_completed_items_preserves_history_dates_and_category() {
    let mut r = Records::new();
    let p = add_project(&mut r, "A");
    let s = stage(&mut r, &p);
    let t = add_task(&mut r, &p, &s);
    apply(
        &mut r,
        Mutation::CompleteTask {
            uid: t.clone(),
            completed: true,
        },
    );
    let before = task(&r, &t);
    let ideas = rules::ideas_uid(&p);
    apply(
        &mut r,
        Mutation::SaveTask {
            uid: Some(t.clone()),
            draft: edit(Some(&p), Some(&ideas)),
        },
    );
    let after = task(&r, &t);
    assert_eq!(after.completions, before.completions);
    assert_eq!(after.status, "已完成");
    assert_eq!(after.range_start, before.range_start);
    assert_eq!(after.category, "学习");
    let mut changed = project("A");
    changed.category = "生活".into();
    apply(
        &mut r,
        Mutation::SaveProject {
            uid: Some(p),
            draft: changed,
        },
    );
    assert_eq!(task(&r, &t).category, "学习");
    apply(
        &mut r,
        Mutation::CompleteTask {
            uid: t.clone(),
            completed: false,
        },
    );
    assert_eq!(task(&r, &t).completions.len(), 1);
}

#[test]
fn nonempty_and_system_stages_cannot_be_deleted_or_retyped() {
    let mut r = Records::new();
    let p = add_project(&mut r, "A");
    let s = stage(&mut r, &p);
    let t = add_task(&mut r, &p, &s);
    apply(
        &mut r,
        Mutation::CompleteTask {
            uid: t.clone(),
            completed: true,
        },
    );
    for id in [&s, &rules::ideas_uid(&p)] {
        assert!(rules::mutate(&mut r.clone(), Mutation::Delete { uid: id.clone() }, AT).is_err());
    }
    let ideas = rules::ideas_uid(&p);
    let mut draft = match r[&ideas].clone() {
        Record::Milestone(Some(m)) => m,
        _ => panic!(),
    };
    draft.stage_kind = StageKind::Standard;
    assert!(rules::mutate(
        &mut r.clone(),
        Mutation::SaveMilestone {
            uid: Some(ideas.clone()),
            draft
        },
        AT
    )
    .is_err());
    apply(
        &mut r,
        Mutation::SaveTask {
            uid: Some(t),
            draft: edit(Some(&p), Some(&ideas)),
        },
    );
    apply(&mut r, Mutation::Delete { uid: s.clone() });
    assert!(r[&s].deleted());
}

#[test]
fn concurrent_stage_deletion_and_new_item_preserves_the_item_in_ideas() {
    let mut base = Records::new();
    let p = add_project(&mut base, "A");
    let s = stage(&mut base, &p);
    let mut local = base.clone();
    let mut remote = base.clone();
    apply(&mut local, Mutation::Delete { uid: s.clone() });
    let t = add_task(&mut remote, &p, &s);
    apply(
        &mut remote,
        Mutation::CompleteTask {
            uid: t.clone(),
            completed: true,
        },
    );
    let (out, conflicts) = sync::merge(&base, &local, &remote, &BTreeMap::new()).unwrap();
    assert!(conflicts.is_empty());
    assert!(out[&s].deleted());
    assert_eq!(task(&out, &t).milestone_id, Some(rules::ideas_uid(&p)));
    assert_eq!(task(&out, &t).completions, task(&remote, &t).completions);
}

#[test]
fn duplicate_upgraded_ideas_stages_converge_without_losing_items() {
    let mut r = Records::new();
    let p = add_project(&mut r, "A");
    let id = rules::ideas_uid(&p);
    let duplicate = "b".repeat(32);
    r.insert(duplicate.clone(), r[&id].clone());
    let t = "c".repeat(32);
    r.insert(
        t.clone(),
        Record::Task(Some(Box::new(Task {
            title: "旧想法".into(),
            project_id: Some(p),
            milestone_id: Some(duplicate.clone()),
            ..Task::default()
        }))),
    );
    rules::normalize(&mut r);
    rules::validate(&r).unwrap();
    assert_eq!(task(&r, &t).milestone_id, Some(id));
    assert!(r[&duplicate].deleted());
}

fn legacy(version: u32) -> Value {
    let p = "a".repeat(32);
    let s = "b".repeat(32);
    let t = "c".repeat(32);
    let mut r = Records::new();
    r.insert(p.clone(), Record::Project(Some(project("旧项目"))));
    r.insert(
        s.clone(),
        Record::Milestone(Some(Milestone {
            stage_kind: StageKind::Standard,
            project_id: p.clone(),
            name: "未来想法".into(),
            acceptance: "原内容".into(),
            position: 1,
            completed_at: None,
        })),
    );
    r.insert(
        t,
        Record::Task(Some(Box::new(Task {
            title: "原事项".into(),
            project_id: Some(p),
            category: "学习".into(),
            notes: "不改内容".into(),
            ..Task::default()
        }))),
    );
    let mut rows = serde_json::to_value(r).unwrap();
    for row in rows.as_object_mut().unwrap().values_mut() {
        let kind = row["kind"].as_str().unwrap().to_owned();
        let f = row["fields"].as_object_mut().unwrap();
        if kind == "projects" {
            f.remove("category");
            if version < 3 {
                f.remove("priority");
                f.remove("mode");
            }
        }
        if kind == "milestones" {
            f.remove("stage_kind");
        }
        if kind == "tasks" && version < 3 {
            for key in ["range_start", "range_end", "excluded_days"] {
                f.remove(key);
            }
        }
    }
    json!({"format":"agent-system-data","version":version,"records":rows})
}

#[test]
fn old_wire_one_to_five_upgrades_and_six_is_strict() {
    let mut expected = None;
    for version in 1..=5 {
        let r = sync::decode(&legacy(version).to_string()).unwrap();
        assert!(matches!(&r[&"a".repeat(32)],Record::Project(Some(p)) if p.category=="其他"));
        assert_eq!(
            task(&r, &"c".repeat(32)).milestone_id,
            Some(rules::ideas_uid(&"a".repeat(32)))
        );
        assert_eq!(task(&r, &"c".repeat(32)).category, "学习");
        let encoded = sync::encode(&r).unwrap();
        assert!(encoded.contains("\"version\": 6"));
        assert_eq!(sync::decode(&encoded).unwrap(), r);
        if version >= 3 {
            if let Some(ref e) = expected {
                assert_eq!(&r, e);
            }
            expected = Some(r);
        }
    }
    let mut malformed = legacy(5);
    malformed["version"] = json!(6);
    assert!(sync::decode(&malformed.to_string()).is_err());
    malformed["version"] = json!(7);
    assert!(sync::decode(&malformed.to_string()).is_err());
    let mut wrong = legacy(5);
    wrong["records"]["a".repeat(32)]["fields"]["category"] = json!("开发");
    assert!(sync::decode(&wrong.to_string()).is_err());
}

#[test]
fn an_unshared_legacy_named_stage_does_not_create_missing_baseline_records() {
    let local = sync::decode(&legacy(5).to_string()).unwrap();
    let mut shared = legacy(5);
    shared["records"].as_object_mut().unwrap().remove(&"b".repeat(32));
    shared["records"].as_object_mut().unwrap().remove(&"c".repeat(32));
    let base = sync::decode(&shared.to_string()).unwrap();
    let (merged, conflicts) = sync::merge(&base, &local, &base, &BTreeMap::new()).unwrap();
    assert!(conflicts.is_empty());
    assert_eq!(task(&merged, &"c".repeat(32)).milestone_id, Some(rules::ideas_uid(&"a".repeat(32))));
    assert!(matches!(&merged[&rules::ideas_uid(&"a".repeat(32))], Record::Milestone(Some(m)) if m.acceptance == "原内容"));
}

fn old_database(path: &std::path::Path) {
    let s = Store::open(path).unwrap();
    drop(s);
    let db = Connection::open(path).unwrap();
    let rows = legacy(5)["records"].as_object().unwrap().clone();
    for (uid, r) in rows {
        db.execute(
            "INSERT INTO records(uid,kind,payload) VALUES(?,?,?)",
            params![uid, r["kind"].as_str().unwrap(), r.to_string()],
        )
        .unwrap();
    }
    db.execute(
        "UPDATE state SET value=? WHERE key='baseline'",
        [legacy(5)["records"].to_string()],
    )
    .unwrap();
    let j = json!({"kind":"job_applications","fields":{"company":"保留公司","title":"岗位","applied_on":"2026-10-17","status":"已投递","url":"","notes":"已有求职数据","interview_at":"","written_at":"","rejected_at":""}});
    db.execute(
        "INSERT INTO records(uid,kind,payload) VALUES(?,'job_applications',?)",
        params!["d".repeat(32), j.to_string()],
    )
    .unwrap();
    db.execute_batch("PRAGMA user_version=1").unwrap();
}

#[test]
fn migration_backs_up_preserves_jobs_ids_and_normalizes_baseline_once() {
    let d = tempfile::tempdir().unwrap();
    let path = d.path().join("a.sqlite3");
    old_database(&path);
    let prior = Connection::open(&path).unwrap();
    let job: String = prior
        .query_row(
            "SELECT payload FROM records WHERE kind='job_applications'",
            [],
            |r| r.get(0),
        )
        .unwrap();
    let id: i64 = prior
        .query_row(
            "SELECT local_id FROM records WHERE uid=?",
            ["c".repeat(32)],
            |r| r.get(0),
        )
        .unwrap();
    drop(prior);
    let s = Store::open(&path).unwrap();
    let snapshot = s.snapshot().unwrap();
    assert_eq!(
        s.db.query_row("PRAGMA user_version", [], |r| r.get::<_, u32>(0))
            .unwrap(),
        2
    );
    assert_eq!(snapshot.local_ids[&"c".repeat(32)], id as u32);
    assert_eq!(
        s.db.query_row(
            "SELECT payload FROM records WHERE kind='job_applications'",
            [],
            |r| r.get::<_, String>(0)
        )
        .unwrap(),
        job
    );
    for (uid, r) in s.baseline().unwrap() {
        assert_eq!(snapshot.records.get(&uid), Some(&r));
    }
    let revision = s.revision().unwrap();
    drop(s);
    let s = Store::open(&path).unwrap();
    assert_eq!(s.revision().unwrap(), revision);
    assert_eq!(
        std::fs::read_dir(d.path().join("backups")).unwrap().count(),
        1
    );
    assert_eq!(snapshot.records, s.snapshot().unwrap().records);
}

#[test]
fn migration_failure_rolls_back_records_baseline_and_version() {
    let d = tempfile::tempdir().unwrap();
    let path = d.path().join("a.sqlite3");
    old_database(&path);
    let db = Connection::open(&path).unwrap();
    let baseline: String = db
        .query_row("SELECT value FROM state WHERE key='baseline'", [], |r| {
            r.get(0)
        })
        .unwrap();
    db.execute_batch("CREATE TRIGGER fail_migration BEFORE UPDATE ON records BEGIN SELECT RAISE(ABORT,'fixed failure'); END;").unwrap();
    drop(db);
    assert!(Store::open(&path).is_err());
    let db = Connection::open(&path).unwrap();
    assert_eq!(
        db.query_row("PRAGMA user_version", [], |r| r.get::<_, u32>(0))
            .unwrap(),
        1
    );
    assert_eq!(
        db.query_row("SELECT value FROM state WHERE key='baseline'", [], |r| {
            r.get::<_, String>(0)
        })
        .unwrap(),
        baseline
    );
    let payload: String = db
        .query_row(
            "SELECT payload FROM records WHERE uid=?",
            ["a".repeat(32)],
            |r| r.get(0),
        )
        .unwrap();
    assert!(!payload.contains("category"));
    db.execute_batch("DROP TRIGGER fail_migration;").unwrap();
    drop(db);
    assert!(Store::open(&path).is_ok());
}
