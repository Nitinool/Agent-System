//! Disposable core benchmark; never opens an installed application's database.
use agent_system::{model::*, store::Database, store::Store, sync::SyncService};
use std::time::Instant;
fn main() -> Result<()> {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("performance.sqlite3");
    let mut store = Store::open(&path)?;
    let mut records = Records::new();
    let project = "f".repeat(32);
    records.insert(
        project.clone(),
        Record::Project(Some(Project {
            name: "固定性能样本".into(),
            goal: String::new(),
            status: "进行中".into(),
            priority: "普通".into(),
            mode: "探索型".into(),
            category: "开发".into(),
        })),
    );
    let day = chrono::Local::now().format("%Y-%m-%d").to_string();
    for i in 1..=1500 {
        let mut task = Task {
            title: format!("事项 {i}"),
            project_id: Some(project.clone()),
            ..Task::default()
        };
        if i <= 150 {
            task.range_start = Some(day.clone());
            task.range_end = Some(day.clone());
            task.planned_on = Some(day.clone());
        }
        records.insert(format!("{i:032x}"), Record::Task(Some(Box::new(task))));
    }
    agent_system::rules::ensure_ideas(&mut records, false);
    store.import(&Records::new(), &records)?;
    let began = Instant::now();
    let snapshot = store.snapshot()?;
    let snapshot_ms = began.elapsed().as_secs_f64() * 1000.0;
    let began = Instant::now();
    store.mutate(
        Mutation::CompleteTask {
            uid: format!("{:032x}", 1),
            completed: true,
        },
        snapshot.revision,
    )?;
    let complete_ms = began.elapsed().as_secs_f64() * 1000.0;
    drop(store);
    let db = Database::start(path)?;
    let sync = SyncService::new(db.clone(), directory.path().into())?;
    sync.status()?;
    let began = Instant::now();
    for _ in 0..100 {
        sync.status()?;
    }
    let idle_status_ms = began.elapsed().as_secs_f64() * 10.0;
    println!(
        "{}",
        serde_json::json!({"tasks":1500,"today":150,"snapshot_ms":snapshot_ms,"complete_ms":complete_ms,"idle_status_average_ms":idle_status_ms,"kind":"debug Rust core, temporary data; not native window timing"})
    );
    drop(sync);
    drop(db);
    std::thread::sleep(std::time::Duration::from_millis(50));
    Ok(())
}
