//! Private GitHub transport, validated wire format and record-level three-way merge.
use crate::{model::*, rules, store::Database};
use base64::{engine::general_purpose::STANDARD, Engine};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{
    collections::BTreeMap,
    io::Read,
    path::PathBuf,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
    time::{Duration, Instant},
};
pub const REPOSITORY: &str = "Nitinool/Agent-System-data";
pub const REMOTE_PATH: &str = "sync/v2/records.json";
pub const MAX_BYTES: usize = 900_000;

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Payload {
    format: String,
    version: u32,
    records: Records,
}
pub fn encode(records: &Records) -> Result<String> {
    rules::validate(records)?;
    let kinds: Vec<_> = records.values().map(Record::kind).collect();
    let version = if kinds.contains(&"job_applications") {
        5
    } else if kinds.contains(&"notes") {
        4
    } else if kinds.contains(&"tasks") || kinds.contains(&"projects") {
        3
    } else if kinds.contains(&"finance_entries") {
        2
    } else {
        1
    };
    let out = serde_json::to_string_pretty(&Payload {
        format: "agent-system-data".into(),
        version,
        records: records.clone(),
    })?;
    if out.len() > MAX_BYTES {
        return Err(AppError::new(
            "size",
            "同步数据超过 900 KB 上限，本地内容仍保留。",
        ));
    }
    Ok(out)
}
// Recursive visitor rejects duplicate JSON keys rather than silently overwriting them.
struct Unique(Value);
impl<'de> Deserialize<'de> for Unique {
    fn deserialize<D: serde::Deserializer<'de>>(
        deserializer: D,
    ) -> std::result::Result<Self, D::Error> {
        struct Visitor;
        impl<'de> serde::de::Visitor<'de> for Visitor {
            type Value = Unique;
            fn expecting(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
                f.write_str("unique JSON keys")
            }
            fn visit_map<M: serde::de::MapAccess<'de>>(
                self,
                mut map: M,
            ) -> std::result::Result<Unique, M::Error> {
                let mut out = serde_json::Map::new();
                while let Some((key, value)) = map.next_entry::<String, Unique>()? {
                    if out.insert(key, value.0).is_some() {
                        return Err(serde::de::Error::custom("duplicate key"));
                    }
                }
                Ok(Unique(Value::Object(out)))
            }
            fn visit_seq<S: serde::de::SeqAccess<'de>>(
                self,
                mut seq: S,
            ) -> std::result::Result<Unique, S::Error> {
                let mut values = vec![];
                while let Some(v) = seq.next_element::<Unique>()? {
                    values.push(v.0);
                }
                Ok(Unique(Value::Array(values)))
            }
            fn visit_bool<E: serde::de::Error>(self, v: bool) -> std::result::Result<Unique, E> {
                Ok(Unique(v.into()))
            }
            fn visit_i64<E: serde::de::Error>(self, v: i64) -> std::result::Result<Unique, E> {
                Ok(Unique(v.into()))
            }
            fn visit_u64<E: serde::de::Error>(self, v: u64) -> std::result::Result<Unique, E> {
                Ok(Unique(v.into()))
            }
            fn visit_f64<E: serde::de::Error>(self, v: f64) -> std::result::Result<Unique, E> {
                serde_json::Number::from_f64(v)
                    .map(|n| Unique(Value::Number(n)))
                    .ok_or_else(|| serde::de::Error::custom("number"))
            }
            fn visit_str<E: serde::de::Error>(self, v: &str) -> std::result::Result<Unique, E> {
                Ok(Unique(v.into()))
            }
            fn visit_string<E: serde::de::Error>(
                self,
                v: String,
            ) -> std::result::Result<Unique, E> {
                Ok(Unique(v.into()))
            }
            fn visit_none<E: serde::de::Error>(self) -> std::result::Result<Unique, E> {
                Ok(Unique(Value::Null))
            }
            fn visit_unit<E: serde::de::Error>(self) -> std::result::Result<Unique, E> {
                Ok(Unique(Value::Null))
            }
        }
        deserializer.deserialize_any(Visitor)
    }
}
pub fn decode(text: &str) -> Result<Records> {
    if text.len() > MAX_BYTES {
        return Err(AppError::validation("远端文件过大。"));
    }
    let Unique(mut value) = serde_json::from_str(text)?;
    let version = value["version"]
        .as_u64()
        .filter(|n| (1..=5).contains(n))
        .ok_or_else(|| AppError::validation("同步版本不受支持。"))?;
    if let Some(records) = value["records"].as_object_mut() {
        for r in records.values_mut() {
            let kind = r["kind"].as_str().unwrap_or("").to_string();
            if (kind == "notes" && version < 4) || (kind == "finance_entries" && version < 2) {
                return Err(AppError::validation("同步格式版本与记录类型不一致。"));
            }
            if let Some(f) = r["fields"].as_object_mut() {
                if version < 3 {
                    if kind == "projects" {
                        if f.contains_key("priority") || f.contains_key("mode") {
                            return Err(AppError::validation("旧格式含新版字段。"));
                        }
                        f.insert("priority".into(), json!("普通"));
                        f.insert("mode".into(), json!("目标型"));
                    }
                    if kind == "tasks" {
                        for key in ["range_start", "range_end", "excluded_days"] {
                            if f.contains_key(key) {
                                return Err(AppError::validation("旧格式含新版字段。"));
                            }
                        }
                        f.insert("range_start".into(), Value::Null);
                        f.insert("range_end".into(), Value::Null);
                        f.insert("excluded_days".into(), json!([]));
                    }
                }
                if version < 5 && kind == "job_applications" {
                    for key in ["interview_at", "written_at", "rejected_at"] {
                        if f.contains_key(key) {
                            return Err(AppError::validation("旧格式含新版字段。"));
                        }
                        f.insert(key.into(), json!(""));
                    }
                }
            }
        }
    }
    let payload: Payload = serde_json::from_value(value)?;
    if payload.format != "agent-system-data" {
        return Err(AppError::validation("远端文件格式不受支持。"));
    }
    rules::validate(&payload.records)?;
    Ok(payload.records)
}
pub fn merge(
    base: &Records,
    local: &Records,
    remote: &Records,
    choices: &BTreeMap<String, String>,
) -> Result<(Records, Vec<Conflict>)> {
    rules::validate(base)?;
    rules::validate(local)?;
    rules::validate(remote)?;
    if base
        .keys()
        .any(|k| !local.contains_key(k) || !remote.contains_key(k))
    {
        return Err(AppError::new(
            "missing_records",
            "同步文件缺少已共享记录，请恢复文件；删除须使用软件。",
        ));
    }
    let ids: std::collections::BTreeSet<_> = local.keys().chain(remote.keys()).collect();
    let mut out = Records::new();
    let mut conflicts = vec![];
    for id in ids {
        let before = base.get(id);
        let ours = local.get(id);
        let theirs = remote.get(id);
        if ours.zip(theirs).is_some_and(|(a, b)| a.kind() != b.kind()) {
            return Err(AppError::validation("同一编号的记录类型发生变化。"));
        }
        let result = if ours == theirs || theirs == before {
            ours
        } else if ours == before {
            theirs
        } else {
            match choices.get(id).map(String::as_str) {
                Some("local") => ours,
                Some("remote") => theirs,
                Some(_) => return Err(AppError::validation("请选择本机或远端版本。")),
                None => {
                    conflicts.push(Conflict {
                        uid: id.clone(),
                        base: before.cloned(),
                        local: ours
                            .cloned()
                            .ok_or_else(|| AppError::validation("本机记录缺失。"))?,
                        remote: theirs
                            .cloned()
                            .ok_or_else(|| AppError::validation("远端记录缺失。"))?,
                    });
                    continue;
                }
            }
        };
        if let Some(r) = result {
            out.insert(id.clone(), r.clone());
        }
    }
    if conflicts.is_empty() {
        rules::normalize(&mut out);
        rules::validate(&out)?;
    }
    Ok((out, conflicts))
}
pub trait Transport: Send {
    fn fetch(&mut self) -> Result<(Records, Option<String>)>;
    fn publish(&mut self, records: &Records, sha: Option<&str>) -> Result<()>;
}
pub struct GitHub {
    token: String,
    client: reqwest::blocking::Client,
    branch: Option<String>,
}
impl GitHub {
    pub fn new(token: String) -> Result<Self> {
        if token.is_empty() || token.chars().any(char::is_whitespace) {
            return Err(AppError::new("credential", "请先配置 GitHub Token。"));
        }
        Ok(Self {
            token,
            client: reqwest::blocking::Client::builder()
                .timeout(Duration::from_secs(20))
                .redirect(reqwest::redirect::Policy::none())
                .build()
                .map_err(|_| AppError::new("network", "网络组件无法启动。"))?,
            branch: None,
        })
    }
    fn request(&self, url: &str, body: Option<Value>) -> Result<(u16, Value)> {
        let request = if let Some(payload) = body {
            self.client.put(url).json(&payload)
        } else {
            self.client.get(url)
        };
        let response = request
            .bearer_auth(&self.token)
            .header("Accept", "application/vnd.github+json")
            .header("User-Agent", "Agent-System-V2")
            .header("X-GitHub-Api-Version", "2022-11-28")
            .send()
            .map_err(|_| AppError::new("network", "连接 GitHub 失败或超时，请重试。"))?;
        let status = response.status().as_u16();
        if status == 404 {
            return Ok((status, Value::Null));
        }
        if status == 409 || status == 422 {
            return Err(AppError::new("remote_changed", "远端已更新，请重新同步。"));
        }
        if status == 401 || status == 403 {
            return Err(AppError::new(
                "credential",
                "GitHub 拒绝访问，请检查 Token 权限、有效期或请求限额。",
            ));
        }
        if !(200..300).contains(&status) {
            return Err(AppError::new("network", "GitHub 请求失败，请稍后重试。"));
        }
        let mut bytes = vec![];
        response
            .take((MAX_BYTES * 2 + 1) as u64)
            .read_to_end(&mut bytes)?;
        if bytes.len() > MAX_BYTES * 2 {
            return Err(AppError::validation("GitHub 响应过大。"));
        }
        Ok((status, serde_json::from_slice(&bytes)?))
    }
    fn check_private(&mut self) -> Result<()> {
        let (_, info) =
            self.request(&format!("https://api.github.com/repos/{REPOSITORY}"), None)?;
        if info["private"] != true {
            return Err(AppError::new(
                "private_required",
                "数据仓库必须私有，或 Token 尚无权访问。",
            ));
        }
        self.branch = info["default_branch"].as_str().map(str::to_string);
        if self.branch.is_none() {
            return Err(AppError::validation("无法确定默认分支。"));
        }
        Ok(())
    }
}
impl Transport for GitHub {
    fn fetch(&mut self) -> Result<(Records, Option<String>)> {
        self.check_private()?;
        let mut url = reqwest::Url::parse(&format!(
            "https://api.github.com/repos/{REPOSITORY}/contents/{REMOTE_PATH}"
        ))
        .unwrap();
        url.query_pairs_mut()
            .append_pair("ref", self.branch.as_deref().unwrap());
        let (status, info) = self.request(url.as_str(), None)?;
        if status == 404 {
            return Ok((Records::new(), None));
        }
        if info["encoding"] != "base64"
            || info["type"] != "file"
            || info["size"].as_u64().unwrap_or(u64::MAX) > MAX_BYTES as u64
        {
            return Err(AppError::validation("同步文件无法读取。"));
        }
        let encoded = info["content"]
            .as_str()
            .ok_or_else(|| AppError::validation("同步内容缺失。"))?
            .replace(['\n', '\r'], "");
        let data = STANDARD
            .decode(encoded)
            .map_err(|_| AppError::validation("同步文件编码无效。"))?;
        let text =
            String::from_utf8(data).map_err(|_| AppError::validation("同步文件不是 UTF-8。"))?;
        let sha = info["sha"]
            .as_str()
            .filter(|s| s.len() == 40)
            .ok_or_else(|| AppError::validation("同步 SHA 无效。"))?;
        Ok((decode(&text)?, Some(sha.into())))
    }
    fn publish(&mut self, records: &Records, sha: Option<&str>) -> Result<()> {
        self.check_private()?;
        let mut payload = json!({"message":"Sync Agent System V2 records","content":STANDARD.encode(encode(records)?),"branch":self.branch});
        if let Some(sha) = sha {
            payload["sha"] = json!(sha);
        }
        let (status, _) = self.request(
            &format!("https://api.github.com/repos/{REPOSITORY}/contents/{REMOTE_PATH}"),
            Some(payload),
        )?;
        if status == 404 {
            return Err(AppError::new("credential", "Token 缺少仓库写入权限。"));
        }
        Ok(())
    }
}

struct Prepared {
    base: Records,
    local: Records,
    remote: Records,
    sha: Option<String>,
}
struct State {
    status: SyncStatus,
    token: String,
    prepared: Option<Prepared>,
    revision: u32,
    changed: Instant,
    next_check: Instant,
    retry_at: Instant,
    failures: u32,
    paused: bool,
}
#[derive(Clone)]
pub struct SyncService {
    db: Database,
    directory: PathBuf,
    state: Arc<Mutex<State>>,
    pub editing: Arc<AtomicBool>,
}
impl SyncService {
    pub fn new(db: Database, directory: PathBuf) -> Result<Self> {
        let path = directory.join("sync-settings.json");
        let settings = if path.exists() {
            serde_json::from_slice::<SyncSettings>(&std::fs::read(path)?)
                .map_err(|_| AppError::validation("新版同步设置损坏，请修复后重启。"))?
        } else {
            SyncSettings::default()
        };
        let token = crate::platform::load_token(&directory.join("sync-token.dpapi"))?;
        Ok(Self {
            db,
            directory,
            state: Arc::new(Mutex::new(State {
                status: SyncStatus {
                    busy: false,
                    pending: 0,
                    message: "尚未检查远端".into(),
                    synced_at: None,
                    conflicts: vec![],
                    settings,
                    has_token: !token.is_empty(),
                },
                token,
                prepared: None,
                revision: u32::MAX,
                changed: Instant::now(),
                next_check: Instant::now() + Duration::from_secs(300),
                retry_at: Instant::now(),
                failures: 0,
                paused: false,
            })),
            editing: Arc::new(AtomicBool::new(false)),
        })
    }
    pub fn status(&self) -> Result<SyncStatus> {
        let revision = self.db.call(|s| s.revision())?;
        let changed = { self.state.lock().unwrap().revision != revision };
        if changed {
            let (snapshot, base, at) = self
                .db
                .call(|s| Ok((s.snapshot()?, s.baseline()?, s.synced_at())))?;
            let pending = snapshot
                .records
                .keys()
                .chain(base.keys())
                .collect::<std::collections::BTreeSet<_>>()
                .iter()
                .filter(|id| snapshot.records.get(**id) != base.get(**id))
                .count() as u32;
            let mut state = self.state.lock().unwrap();
            state.revision = snapshot.revision;
            state.changed = Instant::now();
            state.status.pending = pending;
            state.status.synced_at = at;
        }
        Ok(self.state.lock().unwrap().status.clone())
    }
    pub fn configure(
        &self,
        settings: SyncSettings,
        token: Option<String>,
        remember: bool,
        forget: bool,
    ) -> Result<SyncStatus> {
        let settings_path = self.directory.join("sync-settings.json");
        let temporary = settings_path.with_extension("tmp");
        std::fs::write(&temporary, serde_json::to_vec_pretty(&settings)?)?;
        std::fs::rename(temporary, settings_path)?;
        let mut state = self.state.lock().unwrap();
        if forget {
            crate::platform::save_token(&self.directory.join("sync-token.dpapi"), "")?;
            state.token.clear();
        } else if let Some(token) = token.filter(|t| !t.is_empty()) {
            let _ = GitHub::new(token.clone())?;
            crate::platform::save_token(
                &self.directory.join("sync-token.dpapi"),
                if remember { &token } else { "" },
            )?;
            state.token = token;
        }
        let enabling = settings.auto_sync && !state.status.settings.auto_sync;
        state.status.settings = settings;
        state.status.has_token = !state.token.is_empty();
        state.paused = false;
        if enabling {
            state.next_check = Instant::now();
        }
        state.status.message = "已保存同步设置".into();
        drop(state);
        self.status()
    }
    pub fn run(
        &self,
        check_only: bool,
        automatic: bool,
        choices: BTreeMap<String, String>,
    ) -> Result<SyncStatus> {
        if self.editing.load(Ordering::SeqCst) && !check_only {
            return Err(AppError::new("editing", "请先保存或关闭编辑抽屉后同步。"));
        }
        let token = {
            let mut s = self.state.lock().unwrap();
            if s.status.busy {
                return Err(AppError::new("busy", "同步正在进行。"));
            }
            s.status.busy = true;
            s.status.message = "正在同步…".into();
            s.token.clone()
        };
        let result = (|| {
            let mut transport = GitHub::new(token)?;
            self.execute(&mut transport, check_only, automatic, choices)
        })();
        {
            let mut s = self.state.lock().unwrap();
            s.status.busy = false;
            if let Err(e) = &result {
                s.status.message = e.message.clone();
                s.failures += 1;
                s.retry_at = Instant::now()
                    + Duration::from_secs((30u64 * (1u64 << s.failures.min(4))).min(300));
            }
        }
        result?;
        self.status()
    }
    pub fn execute(
        &self,
        transport: &mut dyn Transport,
        check_only: bool,
        automatic: bool,
        choices: BTreeMap<String, String>,
    ) -> Result<()> {
        let (snapshot, base) = self.db.call(|s| Ok((s.snapshot()?, s.baseline()?)))?;
        let (local, base, remote, sha) = if !choices.is_empty() {
            let mut state = self.state.lock().unwrap();
            let p = state
                .prepared
                .take()
                .ok_or_else(|| AppError::new("conflict", "冲突预览已过期，请重新同步。"))?;
            if snapshot.records != p.local {
                return Err(AppError::new(
                    "local_changed",
                    "预览期间本机有修改，请重新同步。",
                ));
            }
            (p.local, p.base, p.remote, p.sha)
        } else {
            let (remote, sha) = transport.fetch()?;
            (snapshot.records, base, remote, sha)
        };
        if check_only {
            let mut state = self.state.lock().unwrap();
            state.status.message = if remote != base {
                "远端有更新，尚未导入；点击立即同步"
            } else {
                "远端与上次同步一致"
            }
            .into();
            state.next_check = Instant::now() + Duration::from_secs(300);
            return Ok(());
        }
        let (combined, conflicts) = merge(&base, &local, &remote, &choices)?;
        if !conflicts.is_empty() {
            let mut s = self.state.lock().unwrap();
            s.prepared = Some(Prepared {
                base,
                local,
                remote,
                sha,
            });
            s.status.conflicts = conflicts;
            s.paused = automatic;
            s.status.message = "存在冲突，请逐条选择本机或远端版本".into();
            return Ok(());
        }
        if self.editing.load(Ordering::SeqCst) || self.db.call(|s| s.snapshot())?.records != local {
            return Err(AppError::new(
                "local_changed",
                "下载期间本机有修改或正在编辑，请重新同步。",
            ));
        }
        encode(&combined)?;
        if combined != remote {
            transport.publish(&combined, sha.as_deref())?;
        }
        if self.editing.load(Ordering::SeqCst) {
            return Err(AppError::new(
                "editing",
                "远端已保存，本机正在编辑，未覆盖；请再次同步。",
            ));
        }
        let snapshot = self.db.call(move |s| s.import(&local, &combined))?;
        let mut state = self.state.lock().unwrap();
        state.status.pending = 0;
        state.status.synced_at = Some(chrono::Local::now().to_rfc3339());
        state.revision = snapshot.revision;
        state.status.conflicts.clear();
        state.prepared = None;
        state.paused = false;
        state.failures = 0;
        state.retry_at = Instant::now();
        state.next_check = Instant::now() + Duration::from_secs(300);
        state.status.message = "同步完成".into();
        Ok(())
    }
    pub fn cancel_conflicts(&self) {
        let mut s = self.state.lock().unwrap();
        s.prepared = None;
        s.status.conflicts.clear();
        s.paused = true;
        s.status.message = "已取消冲突处理，本地和远端均未修改".into();
    }
    pub fn background_tick(&self, startup: bool) -> Result<bool> {
        let status = self.status()?;
        let run = {
            let s = self.state.lock().unwrap();
            !status.busy
                && status.has_token
                && !s.paused
                && !self.editing.load(Ordering::SeqCst)
                && Instant::now() >= s.retry_at
                && ((startup && (status.settings.check_on_start || status.settings.auto_sync))
                    || (status.settings.auto_sync
                        && s.changed.elapsed() >= Duration::from_secs(5)
                        && (status.pending > 0 || Instant::now() >= s.next_check)))
        };
        if run {
            self.run(startup && !status.settings.auto_sync, true, BTreeMap::new())?;
            return Ok(true);
        }
        Ok(false)
    }
}
