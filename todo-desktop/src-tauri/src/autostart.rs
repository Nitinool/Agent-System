// 开机自启：直接写当前用户的 Run 键，不额外引第三方插件。
use crate::model::{AppError, Result};
use std::ffi::OsStr;
use std::os::windows::ffi::OsStrExt;
use windows_sys::Win32::System::Registry::{
    RegCloseKey, RegDeleteValueW, RegOpenKeyExW, RegQueryValueExW, RegSetValueExW, HKEY,
    HKEY_CURRENT_USER, KEY_READ, KEY_SET_VALUE, REG_SZ,
};

const RUN_KEY: &str = "Software\\Microsoft\\Windows\\CurrentVersion\\Run";
const VALUE_NAME: &str = "TaskNotes";

fn wide(value: &str) -> Vec<u16> {
    OsStr::new(value)
        .encode_wide()
        .chain(std::iter::once(0))
        .collect()
}

fn open(write: bool) -> Option<HKEY> {
    let mut key: HKEY = std::ptr::null_mut();
    let access = if write { KEY_READ | KEY_SET_VALUE } else { KEY_READ };
    let status = unsafe {
        RegOpenKeyExW(
            HKEY_CURRENT_USER,
            wide(RUN_KEY).as_ptr(),
            0,
            access,
            &mut key,
        )
    };
    if status == 0 {
        Some(key)
    } else {
        None
    }
}

pub fn enabled() -> bool {
    let Some(key) = open(false) else {
        return false;
    };
    let mut size = 0u32;
    let status = unsafe {
        RegQueryValueExW(
            key,
            wide(VALUE_NAME).as_ptr(),
            std::ptr::null(),
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            &mut size,
        )
    };
    unsafe { RegCloseKey(key) };
    status == 0
}

pub fn set(enabled: bool) -> Result<()> {
    let key = open(true)
        .ok_or_else(|| AppError::new("autostart", "打不开开机启动项，请检查系统权限。"))?;
    let status = if enabled {
        let exe = std::env::current_exe()
            .map_err(|_| AppError::new("autostart", "无法确定程序所在位置。"))?;
        let command = format!("\"{}\" --hidden", exe.display());
        let data = wide(&command);
        unsafe {
            RegSetValueExW(
                key,
                wide(VALUE_NAME).as_ptr(),
                0,
                REG_SZ,
                data.as_ptr() as *const u8,
                (data.len() * 2) as u32,
            )
        }
    } else {
        unsafe { RegDeleteValueW(key, wide(VALUE_NAME).as_ptr()) }
    };
    unsafe { RegCloseKey(key) };
    // 2 = ERROR_FILE_NOT_FOUND：本来就没有这一项，视为已关闭。
    if status == 0 || (!enabled && status == 2) {
        Ok(())
    } else {
        Err(AppError::new("autostart", "写入开机启动项失败。"))
    }
}
