use agent_system::{
    capture::{clip, csv, merge_display, Activity, Recorder},
    model::Segment,
};
fn activity(title: &str, own: bool) -> Activity {
    Activity {
        pid: if own { 2 } else { 1 },
        process: if own {
            "agent-system.exe"
        } else {
            "chrome.exe"
        }
        .into(),
        title: title.into(),
        own,
    }
}
fn at(second: u32) -> String {
    format!("2026-10-17T12:{:02}:{:02}+08:00", second / 60, second % 60)
}
#[test]
fn switch_uses_monotonic_seconds_and_pause_stops_at_last_sample() {
    let mut r = Recorder::new(1);
    r.sample(Some(activity("A", false)), Some(false), &[], &at(0), 0.0)
        .unwrap();
    r.sample(Some(activity("A", false)), Some(false), &[], &at(1), 1.0)
        .unwrap();
    let switched = r
        .sample(Some(activity("B", false)), Some(false), &[], &at(2), 2.0)
        .unwrap();
    assert_eq!(switched[0].seconds, 2.0);
    let stop = r.stop("暂停");
    assert_eq!(stop[0].seconds, 0.0);
    assert_eq!(stop[0].end.as_deref(), Some(at(2).as_str()));
}
#[test]
fn own_window_is_excluded_and_repeated_own_samples_keep_merge_marker() {
    let mut r = Recorder::new(1);
    r.sample(Some(activity("A", false)), Some(false), &[], &at(0), 0.0)
        .unwrap();
    let first = r
        .sample(Some(activity("App", true)), Some(false), &[], &at(1), 1.0)
        .unwrap()[0]
        .clone();
    r.sample(Some(activity("App", true)), Some(false), &[], &at(2), 2.0)
        .unwrap();
    r.sample(Some(activity("App", true)), Some(false), &[], &at(3), 3.0)
        .unwrap();
    let second = r
        .sample(Some(activity("A", false)), Some(false), &[], &at(4), 4.0)
        .unwrap()[0]
        .clone();
    assert_eq!(second.resume_reason, "查看日志");
    let merged = merge_display(vec![second, first]);
    assert_eq!(merged.len(), 1);
    assert_eq!(merged[0].seconds, 1.0);
}
#[test]
fn unreadable_or_excluded_samples_break_without_fake_duration() {
    let mut r = Recorder::new(1);
    r.sample(Some(activity("A", false)), Some(false), &[], &at(0), 0.0)
        .unwrap();
    let out = r.sample(None, Some(false), &[], &at(1), 1.0).unwrap();
    assert_eq!(out[0].seconds, 0.0);
    assert_eq!(out[0].reason, "窗口不可读取");
    assert!(r.active.is_none());
    r.sample(
        Some(activity("A", false)),
        Some(false),
        &["CHROME.EXE".into()],
        &at(2),
        2.0,
    )
    .unwrap();
    assert!(r.active.is_none());
}
#[test]
fn lock_closes_application_at_last_confirmed_observation() {
    let mut r = Recorder::new(1);
    r.sample(Some(activity("A", false)), Some(false), &[], &at(0), 0.0)
        .unwrap();
    r.sample(Some(activity("A", false)), Some(false), &[], &at(1), 1.0)
        .unwrap();
    let rows = r.sample(None, Some(true), &[], &at(2), 2.0).unwrap();
    assert_eq!(rows[0].seconds, 1.0);
    assert_eq!(rows[0].last_seen, at(1));
    assert_eq!(rows[1].kind, "locked");
    r.sample(None, Some(true), &[], &at(3), 3.0).unwrap();
    assert_eq!(r.active.as_ref().unwrap().seconds, 1.0);
}
#[test]
fn sleep_and_clock_change_create_gaps_without_inflating_application_time() {
    for tick in [30.0, 2.0] {
        let mut r = Recorder::new(1);
        r.sample(Some(activity("A", false)), Some(false), &[], &at(0), 0.0)
            .unwrap();
        let out = r
            .sample(Some(activity("A", false)), Some(false), &[], &at(30), tick)
            .unwrap();
        assert_eq!(out[0].status, "interrupted");
        assert_eq!(out[0].seconds, 0.0);
        assert_eq!(out[1].kind, "gap");
        assert_eq!(out[1].seconds, 0.0);
        assert_eq!(r.active.as_ref().unwrap().seconds, 0.0);
    }
}
#[test]
fn unknown_session_does_not_log_window_or_add_time() {
    let mut r = Recorder::new(1);
    r.sample(Some(activity("A", false)), Some(false), &[], &at(0), 0.0)
        .unwrap();
    let out = r
        .sample(Some(activity("A", false)), None, &[], &at(1), 1.0)
        .unwrap();
    assert_eq!(out[0].seconds, 0.0);
    assert!(r.active.is_none());
}
#[test]
fn midnight_clips_duration_and_csv_escapes_quotes() {
    let mut s = Segment {
        id: 1,
        start: "2026-10-16T23:59:00+08:00".into(),
        last_seen: "2026-10-17T00:01:00+08:00".into(),
        end: Some("2026-10-17T00:01:00+08:00".into()),
        seconds: 120.0,
        app: "浏览器".into(),
        process: "chrome.exe".into(),
        title: "标题,\"文本\"\n换行".into(),
        kind: "activity".into(),
        status: "closed".into(),
        reason: String::new(),
        resume_reason: String::new(),
        category: "未分类".into(),
    };
    clip(&mut s, "2026-10-17").unwrap();
    assert_eq!(s.seconds, 60.0);
    assert!(s.start.contains("00:00:00"));
    let text = csv(&[s]);
    assert!(text.starts_with('\u{feff}'));
    assert!(text.contains("\"\"文本\"\""));
}
#[test]
fn long_or_unconfirmed_interruptions_do_not_merge() {
    let mut r = Recorder::new(1);
    r.sample(Some(activity("A", false)), Some(false), &[], &at(0), 0.0)
        .unwrap();
    let first = r
        .sample(Some(activity("App", true)), Some(false), &[], &at(1), 1.0)
        .unwrap()[0]
        .clone();
    r.sample(
        Some(activity("Other", false)),
        Some(false),
        &[],
        &at(2),
        2.0,
    )
    .unwrap();
    let last = r
        .sample(Some(activity("A", false)), Some(false), &[], &at(3), 3.0)
        .unwrap();
    let latest = last.last().unwrap().clone();
    assert_eq!(merge_display(vec![latest, first]).len(), 2);
}
