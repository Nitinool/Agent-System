//! Deterministic sample state machine. Wall and monotonic clocks are supplied by callers.
use crate::model::*;
use chrono::{DateTime, FixedOffset, NaiveDateTime, TimeZone};

#[derive(Clone, Debug, PartialEq)]
pub struct Activity {
    pub pid: u32,
    pub process: String,
    pub title: String,
    pub own: bool,
}
pub struct Recorder {
    pub active: Option<Segment>,
    last_at: Option<String>,
    last_tick: Option<f64>,
    next_id: i64,
    returning: bool,
    key: String,
}
impl Recorder {
    pub fn new(next_id: i64) -> Self {
        Self {
            active: None,
            last_at: None,
            last_tick: None,
            next_id,
            returning: false,
            key: String::new(),
        }
    }
    pub fn stop(&mut self, reason: &str) -> Vec<Segment> {
        let result = self.finish(reason, false);
        self.last_at = None;
        self.last_tick = None;
        self.returning = false;
        result
    }
    fn finish(&mut self, reason: &str, interrupted: bool) -> Vec<Segment> {
        let mut result = vec![];
        if let Some(mut s) = self.active.take() {
            s.end = Some(s.last_seen.clone());
            s.reason = reason.into();
            s.status = if interrupted { "interrupted" } else { "closed" }.into();
            result.push(s);
        }
        self.key.clear();
        result
    }
    pub fn sample(
        &mut self,
        activity: Option<Activity>,
        locked: Option<bool>,
        excluded: &[String],
        at: &str,
        tick: f64,
    ) -> Result<Vec<Segment>> {
        let now =
            DateTime::parse_from_rfc3339(at).map_err(|_| AppError::validation("采样时间无效。"))?;
        let mut output = vec![];
        let mut delta = self.last_tick.map(|t| tick - t).unwrap_or(0.0);
        if let Some(last) = &self.last_at {
            let old = DateTime::parse_from_rfc3339(last)
                .map_err(|_| AppError::validation("采样时间无效。"))?;
            let wall = (now - old).num_milliseconds() as f64 / 1000.0;
            if !(0.0..=5.0).contains(&delta) || (wall - delta).abs() > 2.0 {
                let start = last.clone();
                output.extend(self.finish("采样中断", true));
                if wall > 0.0 {
                    let mut gap =
                        self.segment(&start, "gap", "", "采集间隔", "睡眠或程序未按时采样");
                    gap.last_seen = at.into();
                    gap.end = Some(at.into());
                    gap.status = "closed".into();
                    output.push(gap);
                }
                delta = 0.0;
                self.returning = false;
            }
        }
        let unavailable = locked.is_none() || (locked == Some(false) && activity.is_none());
        if locked == Some(true) {
            self.returning = false;
            if self.key != "locked" {
                output.extend(self.finish("检测到锁屏或会话断开", false));
            }
            if let Some(s) = self.active.as_mut() {
                s.last_seen = at.into();
                s.seconds += delta;
                output.push(s.clone());
            } else {
                self.key = "locked".into();
                self.active = Some(self.segment(at, "locked", "", "锁屏或会话断开", ""));
                output.push(self.active.clone().unwrap());
            }
        } else if unavailable
            || activity.as_ref().is_some_and(|a| {
                a.own || excluded.iter().any(|x| x.eq_ignore_ascii_case(&a.process))
            })
        {
            let own = activity.as_ref().is_some_and(|a| a.own);
            self.returning = own
                && (self.returning || self.active.as_ref().is_some_and(|s| s.kind == "activity"));
            if !unavailable {
                if let Some(s) = &mut self.active {
                    s.last_seen = at.into();
                    s.seconds += delta;
                }
            }
            output.extend(self.finish(
                if own {
                    "查看日志"
                } else if unavailable {
                    "窗口不可读取"
                } else {
                    "排除进程"
                },
                false,
            ));
        } else if let Some(a) = activity {
            let key = format!("{}:{}:{}", a.pid, a.process.to_lowercase(), a.title);
            if self.key == key {
                if let Some(s) = &mut self.active {
                    s.seconds += delta;
                    s.last_seen = at.into();
                    output.push(s.clone());
                }
            } else {
                if let Some(s) = &mut self.active {
                    s.last_seen = at.into();
                    s.seconds += delta;
                }
                output.extend(self.finish("窗口切换", false));
                let mut s = self.segment(at, "activity", &a.process, &a.title, "");
                s.resume_reason = if self.returning {
                    "查看日志"
                } else {
                    "其他 / 未知"
                }
                .into();
                self.returning = false;
                self.key = key;
                output.push(s.clone());
                self.active = Some(s);
            }
        }
        self.last_at = Some(at.into());
        self.last_tick = Some(tick);
        Ok(output)
    }
    fn segment(
        &mut self,
        at: &str,
        kind: &str,
        process: &str,
        title: &str,
        reason: &str,
    ) -> Segment {
        let id = self.next_id;
        self.next_id += 1;
        Segment {
            id,
            start: at.into(),
            last_seen: at.into(),
            end: None,
            seconds: 0.0,
            app: app_name(process),
            process: process.into(),
            title: title.into(),
            kind: kind.into(),
            status: "running".into(),
            reason: reason.into(),
            resume_reason: String::new(),
            category: "未分类".into(),
        }
    }
}
pub fn app_name(process: &str) -> String {
    match process.to_lowercase().as_str() {
        "chrome.exe" => "浏览器 · Chrome",
        "msedge.exe" => "浏览器 · Edge",
        "firefox.exe" => "浏览器 · Firefox",
        "wow.exe" => "魔兽世界",
        "wowclassic.exe" => "魔兽世界 · 怀旧服",
        "codex.exe" => "Codex",
        "" => "锁屏 / 会话断开",
        _ => process,
    }
    .into()
}
pub fn clip(s: &mut Segment, day: &str) -> Result<()> {
    let parse = |s: &str| {
        DateTime::parse_from_rfc3339(s).map_err(|_| AppError::validation("记录时间无效。"))
    };
    let start = parse(&s.start)?;
    let end = parse(&s.last_seen)?;
    let midnight = NaiveDateTime::new(crate::rules::day(day)?, chrono::NaiveTime::MIN);
    let left = FixedOffset::east_opt(start.offset().local_minus_utc())
        .unwrap()
        .from_local_datetime(&midnight)
        .single()
        .unwrap();
    let right = left + chrono::Duration::days(1);
    let actual_start = start.max(left);
    let actual_end = end.min(right).max(actual_start);
    let whole = (end - start).num_milliseconds().max(0) as f64;
    if whole > 0.0 {
        s.seconds *= (actual_end - actual_start).num_milliseconds().max(0) as f64 / whole;
    }
    s.start = actual_start.to_rfc3339();
    s.last_seen = actual_end.to_rfc3339();
    if s.end.is_some() {
        s.end = Some(s.last_seen.clone());
    }
    Ok(())
}
pub fn csv(rows: &[Segment]) -> String {
    fn quote(s: &str) -> String {
        format!("\"{}\"", s.replace('"', "\"\""))
    }
    let mut out = "\u{feff}开始,结束,秒数,应用,进程,标题,类型,状态,分类\r\n".to_string();
    for s in rows {
        out.push_str(
            &[
                &s.start,
                &s.last_seen,
                &format!("{:.3}", s.seconds),
                &s.app,
                &s.process,
                &s.title,
                &s.kind,
                &s.status,
                &s.category,
            ]
            .iter()
            .map(|v| quote(v))
            .collect::<Vec<_>>()
            .join(","),
        );
        out.push_str("\r\n");
    }
    out
}
pub fn merge_display(mut rows: Vec<Segment>) -> Vec<Segment> {
    rows.reverse();
    let mut out: Vec<Segment> = vec![];
    for row in rows {
        if let Some(previous) = out.last_mut() {
            let gap = DateTime::parse_from_rfc3339(&row.start)
                .ok()
                .zip(DateTime::parse_from_rfc3339(&previous.last_seen).ok())
                .map(|(a, b)| (a - b).num_milliseconds());
            if row.kind == "activity"
                && previous.kind == "activity"
                && previous.process == row.process
                && previous.title == row.title
                && previous.category == row.category
                && previous.reason == "查看日志"
                && row.resume_reason == "查看日志"
                && gap.is_some_and(|g| (0..=120000).contains(&g))
            {
                previous.last_seen = row.last_seen;
                previous.end = row.end;
                previous.seconds += row.seconds;
                previous.status = row.status;
                previous.reason = row.reason;
                continue;
            }
        }
        out.push(row);
    }
    out.reverse();
    out
}
