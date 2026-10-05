"""Explicit, idempotent starter plan for this demo; never runs on app startup."""

from .project_service import ProjectService

DEMO_PROJECT_NAME = "个人记录 Demo · 持续优化"
DEMO_STAGES = (
    ("项目页改版", "可切换里程碑，阶段进度清楚，事项详情可直接查看。", (
        ("确定项目页布局", "高", "保留左侧项目列表，右侧显示当前阶段、事项和成果。"),
        ("加入里程碑与验收条件", "高", "可新增、编辑、删除阶段，并为事项填写验收条件。"),
        ("显示当前阶段进度", "普通", "搜索、筛选和未来想法不影响阶段事项总数。"),
    )),
    ("完成反馈", "事项完成有确认和撤销，完成时间和成果可回看。", (
        ("完成提示与撤销", "普通", "完成后显示确认，撤销恢复进行中或受阻等原状态。"),
        ("记录完成时间和成果", "普通", "新完成记录保存真实时间，重新打开保留事件记录。"),
        ("显示里程碑达成结果", "低", "阶段事项完成后可确认验收，新增未完成事项会重新打开阶段。"),
    )),
    ("使用验证", "日历、今日待办与项目数据一致，并根据实际试用安排下一轮。", (
        ("核对日历与今日待办同步", "高", "三个入口共用同一事项，状态同步且保留安排日期。"),
        ("实际使用一周并整理反馈", "普通", "记录具体使用问题，选出下一轮最值得改进的事项。"),
    )),
)


def create_demo_plan(service: ProjectService) -> int:
    """Insert the full plan once, atomically, leaving existing matching projects alone."""
    db = service.repository.db
    with db:
        existing = db.execute("SELECT id FROM projects WHERE name_key=?", (DEMO_PROJECT_NAME.casefold(),)).fetchone()
        if existing:
            return existing['id']
        project_id = db.execute("INSERT INTO projects(name,name_key,goal,status) VALUES(?,?,?,'进行中')",
            (DEMO_PROJECT_NAME, DEMO_PROJECT_NAME.casefold(), "客观记录生活和时间分配，让记录、求职、事项和项目管理更好用。")).lastrowid
        for position, (name, acceptance, items) in enumerate(DEMO_STAGES):
            milestone_id = db.execute("INSERT INTO milestones(project_id,name,acceptance,position) VALUES(?,?,?,?)",
                                     (project_id, name, acceptance, position)).lastrowid
            for title, priority, condition in items:
                db.execute("""INSERT INTO tasks(title,category,kind,priority,project_id,milestone_id,acceptance)
                    VALUES(?,'开发','功能',?,?,?,?)""", (title, priority, project_id, milestone_id, condition))
        for title in ("项目投入时间统计", "每周项目回顾"):
            db.execute("INSERT INTO tasks(title,category,kind,project_id) VALUES(?,'开发','功能',?)", (title, project_id))
    return project_id
