//! 事项便签的同步：和主应用共用私有仓库，但用独立文件与独立 Token。
use crate::model::{AppError, Label, Result, Task};
use crate::store::Store;
use chrono::{DateTime, Local};
use serde::{Deserialize, Serialize};
use std::path::Path;

const REPOSITORY: &str = "Nitinool/Agent-System-data";
const REMOTE_PATH: &str = "sync/v2/task-notes.json";
const TOKEN_FILE: &str = "sync-token.dpapi";

#[derive(Debug, Default, Serialize, Deserialize)]
struct Payload {
    #[serde(default)]
    version: u32,
    #[serde(default)]
    generated_at: String,
    #[serde(default)]
    tasks: Vec<Task>,
    #[serde(default)]
    labels: Vec<Label>,
}

#[derive(Debug, Deserialize)]
struct Contents {
    #[serde(default)]
    sha: String,
    #[serde(default)]
    content: String,
}

#[derive(Debug, Default, Serialize)]
pub struct Report {
    pub tasks: usize,
    pub labels: usize,
    pub uploaded: bool,
}

// ---------- Token（DPAPI） ----------

#[repr(C)]
struct Blob {
    size: u32,
    data: *mut u8,
}

#[link(name = "crypt32")]
extern "system" {
    fn CryptProtectData(
        input: *const Blob,
        desc: *const u16,
        entropy: *const Blob,
        reserved: *mut std::ffi::c_void,
        prompt: *mut std::ffi::c_void,
        flags: u32,
        output: *mut Blob,
    ) -> i32;
    fn CryptUnprotectData(
        input: *const Blob,
        desc: *mut *mut u16,
        entropy: *const Blob,
        reserved: *mut std::ffi::c_void,
        prompt: *mut std::ffi::c_void,
        flags: u32,
        output: *mut Blob,
    ) -> i32;
}

#[link(name = "kernel32")]
extern "system" {
    fn LocalFree(pointer: *mut std::ffi::c_void) -> *mut std::ffi::c_void;
}

fn crypt(data: &[u8], decrypt: bool) -> Result<Vec<u8>> {
    unsafe {
        let input = Blob {
            size: data.len() as u32,
            data: data.as_ptr() as *mut u8,
        };
        let mut output = Blob {
            size: 0,
            data: std::ptr::null_mut(),
        };
        let ok = if decrypt {
            CryptUnprotectData(
                &input,
                std::ptr::null_mut(),
                std::ptr::null(),
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                1,
                &mut output,
            )
        } else {
            CryptProtectData(
                &input,
                std::ptr::null(),
                std::ptr::null(),
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                1,
                &mut output,
            )
        };
        if ok == 0 {
            return Err(AppError::new(
                "sync",
                "Token 加密或解密失败，请在本机重新配置。",
            ));
        }
        let result = std::slice::from_raw_parts(output.data, output.size as usize).to_vec();
        LocalFree(output.data.cast());
        Ok(result)
    }
}

fn token_path(directory: &Path) -> std::path::PathBuf {
    directory.join(TOKEN_FILE)
}

pub fn has_token(directory: &Path) -> bool {
    token_path(directory).exists()
}

pub fn save_token(directory: &Path, token: &str) -> Result<()> {
    let trimmed = token.trim();
    if trimmed.is_empty() {
        let _ = std::fs::remove_file(token_path(directory));
        return Ok(());
    }
    let encrypted = crypt(trimmed.as_bytes(), false)?;
    std::fs::write(token_path(directory), encrypted)?;
    Ok(())
}

fn load_token(directory: &Path) -> Result<String> {
    let encrypted = std::fs::read(token_path(directory))
        .map_err(|_| AppError::new("sync", "还没有配置同步 Token。"))?;
    let plain = crypt(&encrypted, true)?;
    String::from_utf8(plain).map_err(|_| AppError::new("sync", "Token 数据损坏，请重新配置。"))
}

// ---------- base64 ----------

const ALPHABET: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

fn encode_base64(data: &[u8]) -> String {
    let mut out = String::with_capacity(data.len().div_ceil(3) * 4);
    for chunk in data.chunks(3) {
        let b = [
            chunk[0],
            *chunk.get(1).unwrap_or(&0),
            *chunk.get(2).unwrap_or(&0),
        ];
        let value = ((b[0] as u32) << 16) | ((b[1] as u32) << 8) | b[2] as u32;
        out.push(ALPHABET[(value >> 18) as usize & 63] as char);
        out.push(ALPHABET[(value >> 12) as usize & 63] as char);
        out.push(if chunk.len() > 1 {
            ALPHABET[(value >> 6) as usize & 63] as char
        } else {
            '='
        });
        out.push(if chunk.len() > 2 {
            ALPHABET[value as usize & 63] as char
        } else {
            '='
        });
    }
    out
}

fn decode_base64(text: &str) -> Result<Vec<u8>> {
    let mut table = [255u8; 256];
    for (index, byte) in ALPHABET.iter().enumerate() {
        table[*byte as usize] = index as u8;
    }
    let mut out = Vec::with_capacity(text.len() / 4 * 3);
    let mut buffer = 0u32;
    let mut bits = 0u32;
    for byte in text.bytes() {
        if byte == b'=' || byte.is_ascii_whitespace() {
            continue;
        }
        let value = table[byte as usize];
        if value == 255 {
            return Err(AppError::new("sync", "远端数据编码无法识别。"));
        }
        buffer = (buffer << 6) | value as u32;
        bits += 6;
        if bits >= 8 {
            bits -= 8;
            out.push((buffer >> bits) as u8);
        }
    }
    Ok(out)
}

// ---------- 合并 ----------

fn stamp(value: &str) -> Option<DateTime<chrono::FixedOffset>> {
    DateTime::parse_from_rfc3339(value).ok()
}

/// 单人多设备：整条按 updated_at 取新，不做逐字段合并。
fn is_newer(candidate: &str, current: &str) -> bool {
    match (stamp(candidate), stamp(current)) {
        (Some(a), Some(b)) => a > b,
        _ => candidate > current,
    }
}

fn merge_tasks(local: Vec<Task>, remote: Vec<Task>) -> Vec<Task> {
    let mut merged = std::collections::BTreeMap::new();
    for task in local {
        merged.insert(task.id.clone(), task);
    }
    for task in remote {
        match merged.get(&task.id) {
            Some(current) if !is_newer(&task.updated_at, &current.updated_at) => {}
            _ => {
                merged.insert(task.id.clone(), task);
            }
        }
    }
    let mut tasks: Vec<Task> = merged.into_values().collect();
    tasks.sort_by(|a, b| a.position.cmp(&b.position).then(a.created_at.cmp(&b.created_at)));
    tasks
}

fn merge_labels(local: Vec<Label>, remote: Vec<Label>) -> Vec<Label> {
    let mut merged = std::collections::BTreeMap::new();
    for label in local {
        merged.insert(label.id.clone(), label);
    }
    for label in remote {
        match merged.get(&label.id) {
            Some(current) if !is_newer(&label.updated_at, &current.updated_at) => {}
            _ => {
                merged.insert(label.id.clone(), label);
            }
        }
    }
    let mut labels: Vec<Label> = merged.into_values().collect();
    labels.sort_by_key(|label| label.position);
    labels
}

fn signature(payload: &Payload) -> String {
    let mut parts: Vec<String> = payload
        .tasks
        .iter()
        .map(|task| format!("t:{}:{}:{}", task.id, task.updated_at, task.deleted_at.is_some()))
        .collect();
    parts.extend(
        payload
            .labels
            .iter()
            .map(|label| format!("l:{}:{}", label.id, label.updated_at)),
    );
    parts.sort();
    parts.join("|")
}

// ---------- GitHub ----------

fn client() -> Result<reqwest::blocking::Client> {
    reqwest::blocking::Client::builder()
        .user_agent("task-notes-sync")
        .timeout(std::time::Duration::from_secs(25))
        .build()
        .map_err(|_| AppError::new("sync", "无法创建网络连接。"))
}

fn url() -> String {
    format!("https://api.github.com/repos/{REPOSITORY}/contents/{REMOTE_PATH}")
}

fn fetch(client: &reqwest::blocking::Client, token: &str) -> Result<Option<(String, Payload)>> {
    let response = client
        .get(url())
        .header("Accept", "application/vnd.github+json")
        .header("Authorization", format!("Bearer {token}"))
        .send()
        .map_err(|_| AppError::new("sync", "连不上 GitHub，请检查网络或代理。"))?;
    if response.status() == reqwest::StatusCode::NOT_FOUND {
        return Ok(None);
    }
    if !response.status().is_success() {
        return Err(AppError::new(
            "sync",
            match response.status().as_u16() {
                401 => "Token 无效或已过期。",
                403 => "Token 权限不足，需要该私有仓库的 Contents 读写权限。",
                _ => "读取远端数据失败。",
            },
        ));
    }
    let contents: Contents = response
        .json()
        .map_err(|_| AppError::new("sync", "远端返回格式无法识别。"))?;
    let bytes = decode_base64(&contents.content)?;
    let payload: Payload = serde_json::from_slice(&bytes)
        .map_err(|_| AppError::new("sync", "远端数据不是有效的同步文件，已停止。"))?;
    Ok(Some((contents.sha, payload)))
}

fn upload(
    client: &reqwest::blocking::Client,
    token: &str,
    sha: Option<&str>,
    payload: &Payload,
) -> Result<bool> {
    let body = serde_json::json!({
        "message": "task-notes: sync",
        "content": encode_base64(&serde_json::to_vec_pretty(payload)?),
        "branch": "main",
    });
    let mut body = body;
    if let Some(sha) = sha {
        body["sha"] = serde_json::Value::String(sha.to_string());
    }
    let response = client
        .put(url())
        .header("Accept", "application/vnd.github+json")
        .header("Authorization", format!("Bearer {token}"))
        .json(&body)
        .send()
        .map_err(|_| AppError::new("sync", "上传失败，请检查网络。"))?;
    if !response.status().is_success() {
        return Err(AppError::new(
            "sync",
            match response.status().as_u16() {
                409 | 422 => "远端文件已被别处改动，请再同步一次。",
                401 => "Token 无效或已过期。",
                403 => "Token 权限不足。",
                _ => "上传远端数据失败。",
            },
        ));
    }
    Ok(true)
}

pub fn run(directory: &Path, store: &mut Store) -> Result<Report> {
    let token = load_token(directory)?;
    // 同步前先留一份快照，出问题能回到同步前。
    store.backup_to(&directory.join("tasks.sqlite3"))?;
    let client = client()?;
    let remote = fetch(&client, &token)?;
    let (sha, remote_payload) = match remote {
        Some((sha, payload)) => (Some(sha), payload),
        None => (None, Payload::default()),
    };

    // 先取远端签名，再把它的集合移进合并。
    let remote_signature = signature(&remote_payload);
    let merged_tasks = merge_tasks(store.all_tasks()?, remote_payload.tasks);
    let merged_labels = merge_labels(store.all_labels()?, remote_payload.labels);
    let merged = Payload {
        version: 1,
        generated_at: Local::now().to_rfc3339(),
        tasks: merged_tasks,
        labels: merged_labels,
    };

    let changed = signature(&merged) != remote_signature || sha.is_none();
    let report = Report {
        tasks: merged.tasks.len(),
        labels: merged.labels.len(),
        uploaded: changed,
    };
    // 先落本地再上传，避免上传成功但本地没更新的半截状态。
    store.apply_sync(&merged.tasks, &merged.labels)?;
    if changed {
        upload(&client, &token, sha.as_deref(), &merged)?;
    }
    Ok(report)
}

#[cfg(test)]
#[test]
fn merge_prefers_newer_and_keeps_both_sides() {
    use crate::model::Task;
    let base = |id: &str, updated: &str, deleted: bool| Task {
        id: id.into(),
        project_id: None,
        section_id: None,
        parent_id: None,
        title: format!("{id}-{updated}"),
        notes: String::new(),
        color: "#3b82f6".into(),
        priority: 4,
        start: None,
        end: None,
        recurrence: None,
        repeat_until: None,
        position: 0,
        completed: false,
        completions: vec![],
        included_days: vec![],
        excluded_days: vec![],
        label_ids: vec![],
        deleted_at: if deleted { Some(updated.into()) } else { None },
        created_at: updated.into(),
        updated_at: updated.into(),
    };
    let merged = merge_tasks(
        vec![base("a", "2026-11-20T10:00:00+08:00", false)],
        vec![
            base("a", "2026-11-21T10:00:00+08:00", false),
            base("b", "2026-11-19T10:00:00+08:00", true),
        ],
    );
    assert_eq!(merged.len(), 2);
    let a = merged.iter().find(|task| task.id == "a").unwrap();
    assert!(a.updated_at.starts_with("2026-11-21"));
    let b = merged.iter().find(|task| task.id == "b").unwrap();
    assert!(b.deleted_at.is_some());
}

#[cfg(test)]
#[test]
fn base64_round_trips() {
    for text in ["", "a", "ab", "abc", "任务便签", "{\"a\":1}"] {
        let encoded = encode_base64(text.as_bytes());
        assert_eq!(decode_base64(&encoded).unwrap(), text.as_bytes());
    }
}
