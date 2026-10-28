//! Pure business rules: no UI, files, database or Windows dependencies.
use crate::model::*;
use chrono::{DateTime, NaiveDate, NaiveDateTime};

pub const PRIORITIES: &[&str] = &["紧急", "高", "普通", "低"];
pub const TASK_STATES: &[&str] = &["待开始", "进行中", "受阻", "已完成"];
pub const CATEGORIES: &[&str] = &["其他", "开发", "学习", "求职", "生活", "娱乐", "沟通"];
fn ensure(condition: bool, message: &str) -> Result<()> {
    if condition {
        Ok(())
    } else {
        Err(AppError::validation(message))
    }
}
pub fn day(value: &str) -> Result<NaiveDate> {
    let date = NaiveDate::parse_from_str(value, "%Y-%m-%d")
        .map_err(|_| AppError::validation("日期请使用 YYYY-MM-DD。"))?;
    ensure(
        date.format("%Y-%m-%d").to_string() == value,
        "日期格式不正确。",
    )?;
    Ok(date)
}
fn timestamp(value: &str) -> Result<()> {
    DateTime::parse_from_rfc3339(value)
        .map(|_| ())
        .map_err(|_| AppError::validation("记录时间必须包含时区。"))
}
fn text(value: &str, limit: usize, label: &str) -> Result<()> {
    ensure(
        !value.trim().is_empty() && value.chars().count() <= limit,
        label,
    )
}
pub fn stage_time(value: &str) -> Result<String> {
    let v = value.trim();
    if v.is_empty() {
        return Ok(String::new());
    }
    if v.len() == 10 {
        day(v)?;
        return Ok(v.into());
    }
    ensure(
        v.len() == 16 || v.len() == 19,
        "阶段时间请填写日期或 YYYY-MM-DD HH:MM。",
    )?;
    let normalized = v.replace('T', " ");
    let format = if normalized.len() == 19 {
        "%Y-%m-%d %H:%M:%S"
    } else {
        "%Y-%m-%d %H:%M"
    };
    let at = NaiveDateTime::parse_from_str(&normalized, format)
        .map_err(|_| AppError::validation("阶段时间无效。"))?;
    use chrono::Timelike;
    Ok(at
        .format(if at.second() == 0 {
            "%Y-%m-%d %H:%M"
        } else {
            "%Y-%m-%d %H:%M:%S"
        })
        .to_string())
}
pub fn job_progress(job: &Job, previous: Option<&Job>) -> String {
    if !job.rejected_at.is_empty() {
        return "已拒绝".into();
    }
    if ["已获 Offer", "已撤回"].contains(&job.status.as_str()) {
        return job.status.clone();
    }
    if !job.interview_at.is_empty() {
        return "面试中".into();
    }
    if !job.written_at.is_empty() {
        return "笔试中".into();
    }
    if let Some(old) = previous {
        if old.status == job.status
            && (!old.interview_at.is_empty()
                || !old.written_at.is_empty()
                || !old.rejected_at.is_empty())
            && ["笔试中", "面试中", "已拒绝"].contains(&job.status.as_str())
        {
            return "已投递".into();
        }
    }
    job.status.clone()
}
pub fn valid_uid(uid: &str) -> bool {
    uid.len() == 32
        && uid
            .bytes()
            .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
}
pub fn on_day(task: &Task, date: &str) -> bool {
    task.days.iter().any(|x| x == date)
        || (task.range_start.as_deref().is_some_and(|s| s <= date)
            && task.range_end.as_deref().is_some_and(|e| e >= date)
            && !task.excluded_days.iter().any(|x| x == date))
}
pub fn calendar_day(task: &Task, date: &str) -> bool {
    task.planned_on.as_deref() == Some(date)
        || (task.range_start.as_deref().is_some_and(|s| s <= date)
            && task.range_end.as_deref().is_some_and(|e| e >= date))
}
pub fn validate(records: &Records) -> Result<()> {
    let mut names = std::collections::BTreeSet::new();
    for (uid, record) in records {
        ensure(valid_uid(uid), "同步编号格式无效。")?;
        match record {
            Record::Project(Some(p)) => {
                text(&p.name, 120, "项目名称需为 1–120 字。")?;
                ensure(
                    names.insert(p.name.to_lowercase()),
                    "存在不同编号的同名项目，请先改名。",
                )?;
                ensure(
                    ["进行中", "暂停", "已完成"].contains(&p.status.as_str())
                        && PRIORITIES.contains(&p.priority.as_str())
                        && ["目标型", "探索型"].contains(&p.mode.as_str())
                        && CATEGORIES.contains(&p.category.as_str()),
                    "项目设置无效。",
                )?;
                ensure(records.values().filter(|r| matches!(r, Record::Milestone(Some(m)) if m.project_id == *uid && m.stage_kind == StageKind::Ideas)).count() == 1, "每个项目必须有一个未来想法阶段。")?;
            }
            Record::Milestone(Some(m)) => {
                text(&m.name, 120, "阶段名称需为 1–120 字。")?;
                reference(records, Some(&m.project_id), "projects")?;
                ensure(
                    m.stage_kind != StageKind::Ideas
                        || (m.name == "未来想法"
                            && m.completed_at.is_none()
                            && *uid == ideas_uid(&m.project_id)),
                    "未来想法阶段设置无效。",
                )?;
                if let Some(at) = &m.completed_at {
                    timestamp(at)?;
                    let tasks: Vec<_> = records
                        .values()
                        .filter_map(|r| {
                            if let Record::Task(Some(t)) = r {
                                (t.milestone_id.as_deref() == Some(uid)).then_some(t)
                            } else {
                                None
                            }
                        })
                        .collect();
                    ensure(
                        !tasks.is_empty() && tasks.iter().all(|t| t.status == "已完成"),
                        "阶段仍有未完成事项。",
                    )?;
                }
            }
            Record::Task(Some(t)) => {
                text(&t.title, 120, "事项名称需为 1–120 字。")?;
                ensure(
                    TASK_STATES.contains(&t.status.as_str())
                        && TASK_STATES[..3].contains(&t.resume_status.as_str())
                        && PRIORITIES.contains(&t.priority.as_str())
                        && CATEGORIES.contains(&t.category.as_str())
                        && ["任务", "功能", "问题"].contains(&t.kind.as_str()),
                    "事项设置无效。",
                )?;
                if let Some(d) = &t.planned_on {
                    day(d)?;
                }
                range(t.range_start.as_deref(), t.range_end.as_deref())?;
                dates(&t.days)?;
                dates(&t.excluded_days)?;
                reference(records, t.project_id.as_deref(), "projects")?;
                ensure(
                    t.project_id.is_some() == t.milestone_id.is_some(),
                    "项目事项必须选择所属阶段。",
                )?;
                reference(records, t.milestone_id.as_deref(), "milestones")?;
                if let Some(mid) = &t.milestone_id {
                    if let Some(Record::Milestone(Some(m))) = records.get(mid) {
                        ensure(
                            Some(&m.project_id) == t.project_id.as_ref(),
                            "阶段不属于当前项目。",
                        )?;
                    }
                }
                if let Some(at) = &t.completed_at {
                    ensure(t.status == "已完成", "未完成事项不能有完成时间。")?;
                    timestamp(at)?;
                }
                for event in &t.completions {
                    timestamp(&event.completed_at)?;
                    if let Some(at) = &event.reopened_at {
                        timestamp(at)?;
                    }
                    reference(records, event.project_id.as_deref(), "projects")?;
                }
            }
            Record::Note(Some(n)) => {
                text(&n.title, 500, "随笔需为 1–500 字。")?;
                timestamp(&n.created_at)?;
            }
            Record::Job(Some(j)) => {
                text(&j.title, 120, "请填写岗位名称（最多 120 字）。")?;
                text(&j.company, 120, "请填写公司名称（最多 120 字）。")?;
                day(&j.applied_on)?;
                ensure(
                    [
                        "已投递",
                        "笔试中",
                        "面试中",
                        "已获 Offer",
                        "已拒绝",
                        "已撤回",
                    ]
                    .contains(&j.status.as_str()),
                    "投递进度无效。",
                )?;
                for at in [&j.interview_at, &j.written_at, &j.rejected_at] {
                    ensure(stage_time(at)? == *at, "阶段时间格式不规范。")?;
                }
                ensure(job_progress(j, None) == j.status, "投递进度与时间不一致。")?;
                if !j.url.is_empty() {
                    let url = reqwest::Url::parse(&j.url)
                        .map_err(|_| AppError::validation("岗位链接需使用 http 或 https。"))?;
                    ensure(
                        ["http", "https"].contains(&url.scheme())
                            && url.host_str().is_some()
                            && !j.url.chars().any(char::is_whitespace),
                        "岗位链接无效。",
                    )?;
                }
            }
            Record::Finance(Some(f)) => {
                ensure(
                    f.amount_cents > 0 && f.amount_cents <= 100_000_000_000,
                    "金额必须大于零，且不超过十亿元。",
                )?;
                text(&f.title, 120, "请填写账目名称。")?;
                text(&f.category, 100, "请填写分类。")?;
                day(&f.occurred_on)?;
                ensure(
                    f.side_source.chars().count() <= 100
                        && !["全部来源", "日常收支"].contains(&f.side_source.as_str()),
                    "副业来源无效。",
                )?;
                if f.status == "待结算" {
                    ensure(
                        f.direction == "收入"
                            && !f.side_source.trim().is_empty()
                            && f.settled_on.is_none(),
                        "待结算只适用于尚未到账的副业收入。",
                    )?;
                } else {
                    ensure(
                        (f.direction == "收入" && f.status == "已到账")
                            || (f.direction == "支出" && f.status == "已支付"),
                        "收支状态无效。",
                    )?;
                    let d = f
                        .settled_on
                        .as_deref()
                        .ok_or_else(|| AppError::validation("请填写到账或支付日期。"))?;
                    day(d)?;
                    ensure(d >= f.occurred_on.as_str(), "到账日期不能早于交易日期。")?;
                }
            }
            _ => {}
        }
        let bytes = serde_json::to_vec(record)?;
        ensure(bytes.len() < 200_000, "单条记录过大。")?;
    }
    Ok(())
}
pub fn range(start: Option<&str>, end: Option<&str>) -> Result<()> {
    ensure(start.is_some() == end.is_some(), "请先填写开始日期。")?;
    if let (Some(s), Some(e)) = (start, end) {
        day(s)?;
        day(e)?;
        ensure(e >= s, "结束日期不能早于开始日期。")?;
    }
    Ok(())
}
fn dates(values: &[String]) -> Result<()> {
    for value in values {
        day(value)?;
    }
    ensure(
        values.windows(2).all(|p| p[0] < p[1]),
        "日期不能重复，且必须排序。",
    )
}
fn reference(records: &Records, uid: Option<&str>, kind: &str) -> Result<()> {
    if let Some(id) = uid {
        ensure(
            records
                .get(id)
                .is_some_and(|r| r.kind() == kind && !r.deleted()),
            "关联记录不存在，请刷新后重试。",
        )?;
    }
    Ok(())
}
pub fn normalize(records: &mut Records) {
    let deleted: std::collections::BTreeSet<_> = records
        .iter()
        .filter(|(_, r)| r.deleted())
        .map(|(id, _)| id.clone())
        .collect();
    for record in records.values_mut() {
        if let Record::Milestone(Some(m)) = record {
            if deleted.contains(&m.project_id) {
                *record = Record::Milestone(None);
            }
        }
    }
    let deleted: std::collections::BTreeSet<_> = records
        .iter()
        .filter(|(_, r)| r.deleted())
        .map(|(id, _)| id.clone())
        .collect();
    for record in records.values_mut() {
        if let Record::Task(Some(t)) = record {
            if t.project_id.as_ref().is_some_and(|id| deleted.contains(id)) {
                t.project_id = None;
            }
            if t.milestone_id
                .as_ref()
                .is_some_and(|id| deleted.contains(id))
            {
                t.milestone_id = None;
            }
            for e in &mut t.completions {
                if e.project_id.as_ref().is_some_and(|id| deleted.contains(id)) {
                    e.project_id = None;
                }
            }
        }
    }
    ensure_ideas(records, false);
    let invalid: Vec<_> = records
        .iter()
        .filter_map(|(id, r)| {
            if let Record::Milestone(Some(_)) = r {
                let tasks: Vec<_> = records
                    .values()
                    .filter_map(|r| {
                        if let Record::Task(Some(t)) = r {
                            (t.milestone_id.as_ref() == Some(id)).then_some(t)
                        } else {
                            None
                        }
                    })
                    .collect();
                (matches!(r, Record::Milestone(Some(m)) if m.stage_kind == StageKind::Ideas)
                    || tasks.is_empty()
                    || tasks.iter().any(|t| t.status != "已完成"))
                .then_some(id.clone())
            } else {
                None
            }
        })
        .collect();
    for id in invalid {
        if let Some(Record::Milestone(Some(m))) = records.get_mut(&id) {
            m.completed_at = None;
        }
    }
    let mut companies = std::collections::BTreeMap::<String, String>::new();
    for r in records.values() {
        if let Record::Job(Some(j)) = r {
            let entry = companies
                .entry(j.company.to_lowercase())
                .or_insert(j.company.clone());
            if j.company < *entry {
                *entry = j.company.clone();
            }
        }
    }
    for r in records.values_mut() {
        if let Record::Job(Some(j)) = r {
            if let Some(c) = companies.get(&j.company.to_lowercase()) {
                j.company = c.clone();
            }
        }
    }
}
/// Deterministic system-stage identity also converges independently upgraded peers.
pub fn ideas_uid(project: &str) -> String {
    uuid::Uuid::new_v5(
        &uuid::Uuid::NAMESPACE_URL,
        format!("agent-system-v2/{project}/ideas").as_bytes(),
    )
    .simple()
    .to_string()
}
pub fn ensure_ideas(records: &mut Records, reuse_named: bool) {
    let projects: Vec<_> = records
        .iter()
        .filter_map(|(id, r)| matches!(r, Record::Project(Some(_))).then_some(id.clone()))
        .collect();
    for project in projects {
        let canonical = ideas_uid(&project);
        let mut candidates: Vec<_> = records
            .iter()
            .filter_map(|(id, r)| match r {
                Record::Milestone(Some(m))
                    if m.project_id == project && m.stage_kind == StageKind::Ideas =>
                {
                    Some((id != &canonical, m.position, id.clone(), m.clone()))
                }
                _ => None,
            })
            .collect();
        if candidates.is_empty() && reuse_named {
            candidates = records
                .iter()
                .filter_map(|(id, r)| match r {
                    Record::Milestone(Some(m))
                        if m.project_id == project && m.name == "未来想法" =>
                    {
                        Some((id != &canonical, m.position, id.clone(), m.clone()))
                    }
                    _ => None,
                })
                .collect();
            candidates.sort_by_key(|(_, position, id, _)| (*position, id.clone()));
            candidates.truncate(1);
        } else {
            candidates.sort_by_key(|(noncanonical, position, id, _)| {
                (*noncanonical, *position, id.clone())
            });
        }
        // Preserve legacy stage contents, but canonicalize identity even if it was
        // never shared: baseline/local/remote must generate the same system UID.
        let allowed = match records.get(&canonical) {
            None | Some(Record::Milestone(None)) => true,
            Some(Record::Milestone(Some(m))) => {
                m.project_id == project && candidates.iter().any(|(_, _, id, _)| id == &canonical)
            }
            _ => false,
        };
        if !allowed {
            continue;
        } // Strict validation reports the collision; no overwrite.
        let mut stage = candidates
            .first()
            .map(|(_, _, _, m)| m.clone())
            .unwrap_or(Milestone {
                stage_kind: StageKind::Ideas,
                project_id: project.clone(),
                name: "未来想法".into(),
                acceptance: String::new(),
                position: u32::MAX,
                completed_at: None,
            });
        stage.stage_kind = StageKind::Ideas;
        stage.name = "未来想法".into();
        stage.completed_at = None;
        records.insert(canonical.clone(), Record::Milestone(Some(stage)));
        let duplicates: std::collections::BTreeSet<_> = candidates
            .into_iter()
            .map(|(_, _, id, _)| id)
            .filter(|id| *id != canonical)
            .collect();
        for id in &duplicates {
            records.insert(id.clone(), Record::Milestone(None));
        }
        for r in records.values_mut() {
            if let Record::Task(Some(t)) = r {
                if t.project_id.as_deref() == Some(&project)
                    && (t.milestone_id.is_none()
                        || t.milestone_id
                            .as_ref()
                            .is_some_and(|id| duplicates.contains(id)))
                {
                    t.milestone_id = Some(canonical.clone());
                }
            }
        }
    }
}
fn task_mut<'a>(records: &'a mut Records, uid: &str) -> Result<&'a mut Task> {
    match records.get_mut(uid) {
        Some(Record::Task(Some(t))) => Ok(t),
        _ => Err(AppError::validation("事项已不存在。")),
    }
}
pub fn mutate(records: &mut Records, change: Mutation, at: &str) -> Result<String> {
    let mut uid = uuid::Uuid::new_v4().simple().to_string();
    match change {
        Mutation::SaveProject { uid: id, mut draft } => {
            uid = id.unwrap_or(uid);
            check_existing(records, &uid, "projects")?;
            draft.name = draft.name.trim().into();
            records.insert(uid.clone(), Record::Project(Some(draft)));
        }
        Mutation::SaveMilestone { uid: id, mut draft } => {
            uid = id.unwrap_or(uid);
            check_existing(records, &uid, "milestones")?;
            ensure(
                draft.stage_kind == StageKind::Standard
                    && !matches!(records.get(&uid), Some(Record::Milestone(Some(m))) if m.stage_kind == StageKind::Ideas),
                "未来想法阶段不能重命名或修改类型。",
            )?;
            draft.name = draft.name.trim().into();
            records.insert(uid.clone(), Record::Milestone(Some(draft)));
        }
        Mutation::SaveTask { uid: id, draft } => {
            uid = id.unwrap_or(uid);
            check_existing(records, &uid, "tasks")?;
            let mut task = match records.get(&uid) {
                Some(Record::Task(Some(t))) => t.as_ref().clone(),
                _ => Task::default(),
            };
            ensure(
                draft.project_id.is_some() == draft.milestone_id.is_some(),
                "项目事项必须选择所属阶段。",
            )?;
            task.milestone_id = draft.milestone_id;
            let end = draft.end.or_else(|| draft.start.clone());
            range(draft.start.as_deref(), end.as_deref())?;
            if task.range_start != draft.start || task.range_end != end {
                task.excluded_days.clear();
            }
            task.title = draft.title.trim().into();
            task.notes = draft.notes;
            task.category = draft.category;
            task.project_id = draft.project_id;
            task.planned_on = draft.start.clone();
            task.range_start = draft.start;
            task.range_end = end;
            records.insert(uid.clone(), Record::Task(Some(Box::new(task))));
        }
        Mutation::CompleteTask { uid: id, completed } => {
            uid = id;
            let t = task_mut(records, &uid)?;
            if completed && t.status != "已完成" {
                t.resume_status = t.status.clone();
                t.status = "已完成".into();
                t.completed_at = Some(at.into());
                t.completions.push(Completion {
                    title: t.title.clone(),
                    project_id: t.project_id.clone(),
                    completed_at: at.into(),
                    reopened_at: None,
                });
            } else if !completed && t.status == "已完成" {
                t.status = t.resume_status.clone();
                t.completed_at = None;
                for event in &mut t.completions {
                    if event.reopened_at.is_none() {
                        event.reopened_at = Some(at.into());
                    }
                }
            }
        }
        Mutation::UndoTask {
            uid: id,
            expected,
            previous,
        } => {
            uid = id;
            let t = task_mut(records, &uid)?;
            ensure(*t == *expected, "事项已被修改，无法撤销旧操作。")?;
            // Undo reopens the task but retains the real completion history.
            if t.status == "已完成" && previous.status != "已完成" {
                t.status = previous.status;
                t.resume_status = previous.resume_status;
                t.completed_at = None;
                for e in &mut t.completions {
                    if e.reopened_at.is_none() {
                        e.reopened_at = Some(at.into());
                    }
                }
            } else if t.status != "已完成" && previous.status == "已完成" {
                t.status = "已完成".into();
                t.completed_at = previous.completed_at;
                if let Some(e) = t.completions.last_mut() {
                    e.reopened_at = None;
                }
            }
        }
        Mutation::ArrangeTask {
            uid: id,
            start,
            end,
        } => {
            uid = id;
            let end = end.or_else(|| start.clone());
            range(start.as_deref(), end.as_deref())?;
            let t = task_mut(records, &uid)?;
            t.planned_on = start.clone();
            t.range_start = start;
            t.range_end = end;
            t.excluded_days.clear();
            if let (Some(s), Some(e)) = (&t.range_start, &t.range_end) {
                t.days.retain(|d| d < s || d > e);
            }
        }
        Mutation::Today {
            uid: id,
            day: d,
            included,
        } => {
            uid = id;
            day(&d)?;
            let t = task_mut(records, &uid)?;
            let in_range = t.range_start.as_ref().is_some_and(|s| s <= &d)
                && t.range_end.as_ref().is_some_and(|e| e >= &d);
            t.days.retain(|v| v != &d);
            t.excluded_days.retain(|v| v != &d);
            if in_range && !included {
                t.excluded_days.push(d);
            } else if !in_range && included {
                if t.planned_on.is_none() {
                    t.planned_on = Some(d.clone());
                }
                t.days.push(d);
            }
            t.days.sort();
            t.excluded_days.sort();
        }
        Mutation::AddNote { title } => {
            records.insert(
                uid.clone(),
                Record::Note(Some(Note {
                    title: title.trim().into(),
                    created_at: at.into(),
                })),
            );
        }
        Mutation::SaveJob { uid: id, mut draft } => {
            uid = id.unwrap_or(uid);
            check_existing(records, &uid, "job_applications")?;
            draft.company = draft.company.trim().into();
            draft.title = draft.title.trim().into();
            draft.url = draft.url.trim().into();
            draft.interview_at = stage_time(&draft.interview_at)?;
            draft.written_at = stage_time(&draft.written_at)?;
            draft.rejected_at = stage_time(&draft.rejected_at)?;
            let old = match records.get(&uid) {
                Some(Record::Job(Some(j))) => Some(j),
                _ => None,
            };
            draft.status = job_progress(&draft, old);
            records.insert(uid.clone(), Record::Job(Some(draft)));
        }
        Mutation::SaveFinance { uid: id, draft } => {
            uid = id.unwrap_or(uid);
            check_existing(records, &uid, "finance_entries")?;
            records.insert(uid.clone(), Record::Finance(Some(draft)));
        }
        Mutation::Settle {
            uid: id,
            day,
            amount_cents,
        } => {
            uid = id;
            match records.get_mut(&uid) {
                Some(Record::Finance(Some(f))) if f.status == "待结算" => {
                    f.status = "已到账".into();
                    f.settled_on = Some(day);
                    f.amount_cents = amount_cents;
                }
                _ => return Err(AppError::validation("这条收入已结算或不存在。")),
            }
        }
        Mutation::Delete { uid: id } => {
            uid = id;
            let r = records
                .get(&uid)
                .ok_or_else(|| AppError::validation("记录不存在。"))?;
            if let Record::Milestone(Some(m)) = r {
                ensure(m.stage_kind != StageKind::Ideas, "未来想法阶段不能删除。")?;
                ensure(!records.values().any(|r| matches!(r, Record::Task(Some(t)) if t.milestone_id.as_ref() == Some(&uid))), "阶段中还有事项，请先移动或删除其中事项。")?;
            }
            records.insert(uid.clone(), r.tombstone());
        }
    }
    normalize(records);
    validate(records)?;
    Ok(uid)
}
fn check_existing(records: &Records, uid: &str, kind: &str) -> Result<()> {
    if let Some(r) = records.get(uid) {
        ensure(r.kind() == kind && !r.deleted(), "记录类型不一致或已删除。")?;
    }
    Ok(())
}
