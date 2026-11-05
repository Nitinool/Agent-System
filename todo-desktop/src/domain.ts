import type { Task } from "./bindings/Task";
import type { Draft } from "./bindings/Draft";
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
export const categories = [
  "其他",
  "开发",
  "学习",
  "生活",
  "工作",
  "求职",
  "娱乐",
];
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
export function onDay(t: Task, day: string): boolean {
  return (
    !t.excluded_days.includes(day) &&
    (t.included_days.includes(day) ||
      (!!t.start && t.start <= day && day <= (t.end || t.start)))
  );
}
export function newDraft(day = today(), color = colors[0]): Draft {
  return {
    title: "",
    start: day,
    end: null,
    category: "其他",
    color,
    notes: "",
  };
}
export function sortTasks(items: Task[]) {
  return [...items].sort(
    (a, b) =>
      Number(a.completed) - Number(b.completed) ||
      a.created_at.localeCompare(b.created_at) ||
      a.id.localeCompare(b.id),
  );
}
