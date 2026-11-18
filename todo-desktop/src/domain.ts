import type { Task } from "./bindings/Task";
import type { TaskDraft } from "./bindings/TaskDraft";

export const colors = [
  "#3b82f6",
  "#8b5cf6",
  "#0891b2",
  "#ca8a04",
  "#db2777",
  "#16a34a",
  "#ea580c",
  "#475569",
];

export const priorities = [1, 2, 3, 4] as const;

export function priorityColor(priority: number): string {
  return priority === 1
    ? "#dc2626"
    : priority === 2
      ? "#ea580c"
      : priority === 3
        ? "#2563eb"
        : "transparent";
}
export function priorityName(priority: number): string {
  return priority === 1 ? "P1" : priority === 2 ? "P2" : priority === 3 ? "P3" : "P4";
}
export function priorityTitle(priority: number): string {
  return priority === 1
    ? "最高优先级"
    : priority === 2
      ? "高优先级"
      : priority === 3
        ? "中优先级"
        : "无优先级";
}

export function today(now = new Date()): string {
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

export function shiftDay(day: string, delta: number) {
  const date = new Date(day + "T12:00:00");
  date.setDate(date.getDate() + delta);
  return today(date);
}

export function monthCells(month: string) {
  const first = month + "-01",
    weekday = (new Date(first + "T12:00:00").getDay() + 6) % 7;
  return Array.from({ length: 42 }, (_, i) => shiftDay(first, i - weekday));
}

/** 事项是否落在某一天：显式排除优先，其次显式加入，最后看日期范围。 */
export function onDay(t: Task, day: string): boolean {
  return (
    !t.excluded_days.includes(day) &&
    (t.included_days.includes(day) ||
      (!!t.start && t.start <= day && day <= (t.end || t.start)))
  );
}

/** 按标签筛选：没选任何标签时返回全部，否则只要命中其中任意一个。 */
export function filterByLabels(items: readonly Task[], selected: readonly string[]) {
  if (!selected.length) return [...items];
  const wanted = new Set(selected);
  return items.filter((task) => task.label_ids.some((id) => wanted.has(id)));
}

/** 时间分组内部：按开始日期排，无日期的沉底，同日期保持手动顺序。 */
export function sortBucket(items: readonly Task[]) {
  return [...items].sort(
    (a, b) =>
      (a.start ?? "9999-12-31").localeCompare(b.start ?? "9999-12-31") ||
      a.position - b.position ||
      a.id.localeCompare(b.id),
  );
}

export function inProject(t: Task, projectId: string | null) {
  return t.project_id === projectId;
}

export type Bucket = "overdue" | "today" | "tomorrow" | "week" | "later" | "none";
export const bucketOrder: Bucket[] = ["overdue", "today", "tomorrow", "week", "later", "none"];
export const bucketTitles: Record<Bucket, string> = {
  overdue: "已过期",
  today: "今天",
  tomorrow: "明天",
  week: "本周内",
  later: "以后",
  none: "待安排",
};

/** 一条事项只归一个时间桶：先看是否已过期，再按今天 / 明天 / 七天内 / 以后 / 待安排。 */
export function bucketOf(t: Task, day: string): Bucket {
  if (!t.start && !t.end) return "none";
  const start = t.start ?? t.end ?? day;
  const end = t.end ?? start;
  if (end < day) return "overdue";
  if (onDay(t, day)) return "today";
  if (onDay(t, shiftDay(day, 1))) return "tomorrow";
  if (start <= shiftDay(day, 7)) return "week";
  return "later";
}

export function newDraft(day = today(), color = colors[0]): TaskDraft {
  return {
    title: "",
    notes: "",
    color,
    priority: 4,
    start: day,
    end: null,
    project_id: null,
    section_id: null,
    parent_id: null,
    label_ids: [],
  };
}

/** 未完成在前，其余按手动顺序；不修改原数组。 */
export function sortTasks(items: readonly Task[]) {
  return [...items].sort(
    (a, b) =>
      Number(a.completed) - Number(b.completed) ||
      a.position - b.position ||
      a.created_at.localeCompare(b.created_at) ||
      a.id.localeCompare(b.id),
  );
}

/** 把扁平列表排成父子顺序，父事项在前，子事项缩进紧随其后。 */
export function orderedTree(
  tasks: readonly Task[],
): Array<{ task: Task; depth: number }> {
  const sorted = sortTasks(tasks);
  const ids = new Set(sorted.map((t) => t.id));
  const children = new Map<string, Task[]>();
  const roots: Task[] = [];
  for (const task of sorted) {
    if (task.parent_id && ids.has(task.parent_id)) {
      const list = children.get(task.parent_id);
      if (list) list.push(task);
      else children.set(task.parent_id, [task]);
    } else {
      roots.push(task);
    }
  }
  const out: Array<{ task: Task; depth: number }> = [];
  const walk = (list: readonly Task[], depth: number) => {
    for (const task of list) {
      out.push({ task, depth });
      if (depth < 8) walk(children.get(task.id) ?? [], depth + 1);
    }
  };
  walk(roots, 0);
  return out;
}

const weekdays = ["日", "一", "二", "三", "四", "五", "六"];
export function weekdayShort(day: string): string {
  return weekdays[new Date(day + "T12:00:00").getDay()];
}
export function dayLabel(day: string): string {
  const date = new Date(day + "T12:00:00");
  return `${date.getMonth() + 1}月${date.getDate()}日 周${weekdays[date.getDay()]}`;
}

export function shortDay(day: string): string {
  return `${Number(day.slice(5, 7))}/${Number(day.slice(8, 10))}`;
}

/** 父事项候选：同项目内、排除自己和自己的后代。 */
export function parentOptions(tasks: readonly Task[], selfId: string | null) {
  const excluded = new Set<string>();
  if (selfId) {
    excluded.add(selfId);
    let changed = true;
    while (changed) {
      changed = false;
      for (const task of tasks) {
        if (task.parent_id && excluded.has(task.parent_id) && !excluded.has(task.id)) {
          excluded.add(task.id);
          changed = true;
        }
      }
    }
  }
  return sortTasks(tasks).filter((task) => !excluded.has(task.id));
}
