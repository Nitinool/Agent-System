//! Narrow Windows adapter. Raw handles never leave this module.
use crate::{capture::Activity, model::*};
use std::path::Path;

pub fn save_token(path: &Path, token: &str) -> Result<()> {
    if token.is_empty() {
        if path.exists() {
            std::fs::remove_file(path)?;
        }
        return Ok(());
    }
    if token.chars().any(char::is_whitespace) {
        return Err(AppError::validation("Token 不能包含空白。"));
    }
    let encrypted = crypt(token.as_bytes(), false)?;
    let temporary = path.with_extension("tmp");
    std::fs::write(&temporary, encrypted)?;
    std::fs::rename(temporary, path)?;
    Ok(())
}
pub fn load_token(path: &Path) -> Result<String> {
    if !path.exists() {
        return Ok(String::new());
    }
    String::from_utf8(crypt(&std::fs::read(path)?, true)?)
        .map_err(|_| AppError::new("credential", "Token 无法解密，请重新配置。"))
}
#[cfg(windows)]
pub fn open_url(url: &str) -> Result<()> {
    let parsed = reqwest::Url::parse(url).map_err(|_| AppError::validation("链接无效。"))?;
    if !["https", "http"].contains(&parsed.scheme()) || parsed.host_str().is_none() {
        return Err(AppError::validation("只允许 http / https 链接。"));
    }
    #[link(name = "shell32")]
    unsafe extern "system" {
        fn ShellExecuteW(
            window: isize,
            operation: *const u16,
            file: *const u16,
            parameters: *const u16,
            directory: *const u16,
            show: i32,
        ) -> isize;
    }
    let operation: Vec<u16> = "open\0".encode_utf16().collect();
    let file: Vec<u16> = url.encode_utf16().chain(Some(0)).collect();
    if unsafe {
        ShellExecuteW(
            0,
            operation.as_ptr(),
            file.as_ptr(),
            std::ptr::null(),
            std::ptr::null(),
            1,
        )
    } > 32
    {
        Ok(())
    } else {
        Err(AppError::new("open_url", "无法打开默认浏览器。"))
    }
}
#[cfg(not(windows))]
pub fn open_url(_url: &str) -> Result<()> {
    Err(AppError::new("platform", "此版本只支持 Windows。"))
}
#[cfg(not(windows))]
fn crypt(_: &[u8], _: bool) -> Result<Vec<u8>> {
    Err(AppError::new("platform", "此版本仅支持 Windows 凭据加密。"))
}
#[cfg(not(windows))]
pub fn observation() -> (Option<Activity>, Option<bool>) {
    (None, None)
}

#[cfg(windows)]
mod win {
    use super::*;
    use std::{ffi::c_void, mem::size_of};
    type Handle = isize;
    #[repr(C)]
    struct Blob {
        size: u32,
        data: *mut u8,
    }
    #[repr(C)]
    struct ProcessEntry {
        size: u32,
        usage: u32,
        pid: u32,
        heap: usize,
        module: u32,
        threads: u32,
        parent: u32,
        priority: i32,
        flags: u32,
        exe: [u16; 260],
    }
    #[link(name = "user32")]
    unsafe extern "system" {
        fn GetForegroundWindow() -> Handle;
        fn GetWindowTextW(window: Handle, text: *mut u16, max: i32) -> i32;
        fn GetWindowThreadProcessId(window: Handle, pid: *mut u32) -> u32;
        fn GetAncestor(window: Handle, flags: u32) -> Handle;
    }
    #[link(name = "kernel32")]
    unsafe extern "system" {
        fn OpenProcess(access: u32, inherit: i32, pid: u32) -> Handle;
        fn QueryFullProcessImageNameW(
            process: Handle,
            flags: u32,
            text: *mut u16,
            size: *mut u32,
        ) -> i32;
        fn CloseHandle(handle: Handle) -> i32;
        fn LocalFree(memory: *mut c_void) -> *mut c_void;
        fn CreateToolhelp32Snapshot(flags: u32, pid: u32) -> Handle;
        fn Process32FirstW(snapshot: Handle, entry: *mut ProcessEntry) -> i32;
        fn Process32NextW(snapshot: Handle, entry: *mut ProcessEntry) -> i32;
    }
    #[link(name = "wtsapi32")]
    unsafe extern "system" {
        fn WTSQuerySessionInformationW(
            server: Handle,
            session: u32,
            class: u32,
            buffer: *mut *mut u8,
            size: *mut u32,
        ) -> i32;
        fn WTSFreeMemory(buffer: *mut c_void);
    }
    #[link(name = "crypt32")]
    unsafe extern "system" {
        fn CryptProtectData(
            input: *const Blob,
            desc: *const u16,
            entropy: *const Blob,
            reserved: *mut c_void,
            prompt: *mut c_void,
            flags: u32,
            output: *mut Blob,
        ) -> i32;
        fn CryptUnprotectData(
            input: *const Blob,
            desc: *mut *mut u16,
            entropy: *const Blob,
            reserved: *mut c_void,
            prompt: *mut c_void,
            flags: u32,
            output: *mut Blob,
        ) -> i32;
    }
    struct OwnedHandle(Handle);
    impl Drop for OwnedHandle {
        fn drop(&mut self) {
            unsafe {
                CloseHandle(self.0);
            }
        }
    }
    pub fn crypt(data: &[u8], decrypt: bool) -> Result<Vec<u8>> {
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
                    "credential",
                    "Windows 凭据加密或解密失败，请在本机重新配置 Token。",
                ));
            }
            let result = std::slice::from_raw_parts(output.data, output.size as usize).to_vec();
            LocalFree(output.data.cast());
            Ok(result)
        }
    }
    fn is_own(pid: u32) -> bool {
        if pid == std::process::id() {
            return true;
        }
        unsafe {
            let handle = CreateToolhelp32Snapshot(2, 0);
            if handle == -1 {
                return false;
            }
            let _guard = OwnedHandle(handle);
            let mut entry: ProcessEntry = std::mem::zeroed();
            entry.size = size_of::<ProcessEntry>() as u32;
            let mut parents = std::collections::HashMap::new();
            let mut ok = Process32FirstW(handle, &mut entry);
            while ok != 0 {
                parents.insert(entry.pid, entry.parent);
                ok = Process32NextW(handle, &mut entry);
            }
            let mut ancestor = pid;
            for _ in 0..64 {
                if let Some(parent) = parents.get(&ancestor) {
                    if *parent == std::process::id() {
                        return true;
                    }
                    if *parent == ancestor || *parent == 0 {
                        break;
                    }
                    ancestor = *parent;
                } else {
                    break;
                }
            }
        }
        false
    }
    pub fn observation() -> (Option<Activity>, Option<bool>) {
        unsafe {
            let mut buffer = std::ptr::null_mut();
            let mut bytes = 0;
            let locked =
                if WTSQuerySessionInformationW(0, u32::MAX, 25, &mut buffer, &mut bytes) != 0 {
                    let result = if !buffer.is_null() && bytes >= 20 {
                        let level = std::ptr::read_unaligned(buffer.cast::<u32>());
                        let state = std::ptr::read_unaligned(buffer.add(12).cast::<u32>());
                        let flags = std::ptr::read_unaligned(buffer.add(16).cast::<u32>());
                        if level == 1 && flags <= 1 {
                            Some(flags == 0 || state != 0)
                        } else {
                            None
                        }
                    } else {
                        None
                    };
                    WTSFreeMemory(buffer.cast());
                    result
                } else {
                    None
                };
            if locked != Some(false) {
                return (None, locked);
            }
            let hwnd = GetForegroundWindow();
            if hwnd == 0 {
                return (None, locked);
            }
            let root = GetAncestor(hwnd, 2);
            let mut pid = 0;
            GetWindowThreadProcessId(if root == 0 { hwnd } else { root }, &mut pid);
            if pid == 0 {
                return (None, locked);
            }
            let mut title = vec![0u16; 32768];
            let count =
                GetWindowTextW(hwnd, title.as_mut_ptr(), title.len() as i32).max(0) as usize;
            let mut process = format!("未知程序 (PID {pid})");
            let handle = OpenProcess(0x1000, 0, pid);
            if handle != 0 {
                let _guard = OwnedHandle(handle);
                let mut path = vec![0u16; 32768];
                let mut size = path.len() as u32;
                if QueryFullProcessImageNameW(handle, 0, path.as_mut_ptr(), &mut size) != 0 {
                    process = Path::new(&String::from_utf16_lossy(&path[..size as usize]))
                        .file_name()
                        .unwrap_or_default()
                        .to_string_lossy()
                        .into_owned();
                }
            }
            if hwnd != GetForegroundWindow() {
                return (None, locked);
            }
            (
                Some(Activity {
                    pid,
                    process,
                    title: String::from_utf16_lossy(&title[..count]),
                    own: is_own(pid),
                }),
                locked,
            )
        }
    }
}
#[cfg(windows)]
use win::crypt;
#[cfg(windows)]
pub use win::observation;
