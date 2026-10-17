fn main() {
    #[cfg(feature = "desktop")]
    {
        // tauri-winres escapes apostrophes as path separators in RC icon paths.
        // Keep the checkout in place; stage only the public icon at an ASCII path.
        let attributes = if cfg!(windows) {
            use std::hash::{Hash, Hasher};
            let mut hash = std::collections::hash_map::DefaultHasher::new();
            std::env::var("CARGO_MANIFEST_DIR").unwrap().hash(&mut hash);
            let public = std::path::PathBuf::from(
                std::env::var_os("PUBLIC").unwrap_or_else(|| "C:\\Users\\Public".into()),
            );
            let stage = public
                .join("Agent-System-build")
                .join(format!("{:x}", hash.finish()));
            std::fs::create_dir_all(&stage).expect("create icon staging directory");
            let icon = stage.join("icon.ico");
            std::fs::copy("icons/icon.ico", &icon).expect("stage application icon");
            tauri_build::Attributes::new()
                .windows_attributes(tauri_build::WindowsAttributes::new().window_icon_path(icon))
        } else {
            tauri_build::Attributes::new()
        };
        tauri_build::try_build(attributes).expect("Tauri build helpers");
    }
}
