use crate::model::{AppError, Result};
use std::path::{Path, PathBuf};
pub fn data_directory() -> Result<PathBuf> {
    let root = std::env::var_os("LOCALAPPDATA")
        .ok_or_else(|| AppError::new("directory", "无法确定本机数据目录。"))?;
    checked_directory(Path::new(&root))
}
pub fn checked_directory(root: &Path) -> Result<PathBuf> {
    let directory = root.join("Task-Notes");
    let physical = std::fs::canonicalize(if directory.exists() { &directory } else { root })?;
    let parts: Vec<_> = physical
        .components()
        .map(|p| p.as_os_str().to_string_lossy().to_ascii_lowercase())
        .collect();
    if parts
        .windows(4)
        .any(|p| p[0] == "packages" && p[2] == "localcache" && p[3] == "local")
    {
        return Err(AppError::new("directory_redirected", "启动环境重定向了资料目录。请在文件资源管理器中双击“启动事项便签.cmd”，以免创建另一份隔离数据。"));
    }
    Ok(directory)
}
