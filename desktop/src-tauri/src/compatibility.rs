//! Upgrade only V2 payloads or explicitly decoded older sync formats.
use crate::{model::*, rules};
use serde_json::{json, Value};

pub fn upgrade_fields(records: &mut Value) -> Result<()> {
    let rows = records
        .as_object_mut()
        .ok_or_else(|| AppError::validation("记录格式无效。"))?;
    for record in rows.values_mut() {
        let kind = record["kind"].as_str().unwrap_or("").to_owned();
        if let Some(fields) = record["fields"].as_object_mut() {
            let key = match kind.as_str() {
                "projects" => "category",
                "milestones" => "stage_kind",
                _ => continue,
            };
            if fields.contains_key(key) {
                return Err(AppError::validation("旧格式含新版项目字段。"));
            }
            fields.insert(
                key.into(),
                if kind == "projects" {
                    json!("其他")
                } else {
                    json!("standard")
                },
            );
        }
    }
    Ok(())
}

pub fn legacy_records(mut value: Value) -> Result<Records> {
    upgrade_fields(&mut value)?;
    let mut records: Records = serde_json::from_value(value)?;
    // Reuse a pre-existing named stage only during the legacy upgrade.
    rules::ensure_ideas(&mut records, true);
    rules::validate(&records)?;
    Ok(records)
}
