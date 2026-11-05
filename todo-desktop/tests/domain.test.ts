import { describe, expect, it } from "vitest";
import {
  monthCells,
  newDraft,
  onDay,
  shiftDay,
  sortTasks,
  today,
} from "../src/domain";
import type { Task } from "../src/bindings/Task";
const task = (overrides: Partial<Task> = {}): Task => ({
  ...newDraft("2026-11-04"),
  id: "one",
  completed: false,
  created_at: "2026-11-04T08:00:00+08:00",
  updated_at: "2026-11-04T08:00:00+08:00",
  completions: [],
  included_days: [],
  excluded_days: [],
  ...overrides,
});
describe("独立事项的日期与完成显示", () => {
  it("新增始终默认本地今天，即便当前月历选择了其他日期", () => {
    const local = new Date(2026, 10, 4, 0, 5);
    expect(today(local)).toBe("2026-11-04");
    expect(newDraft().start).toBe(today());
    expect(newDraft().end).toBeNull();
  });
  it("便签仅显示当天，支持单日、范围、显式添加与移出，完成不消失", () => {
    expect(onDay(task(), "2026-11-04")).toBe(true);
    expect(onDay(task(), "2026-11-05")).toBe(false);
    const t = task({ start: "2026-11-01", end: "2026-11-07", completed: true });
    expect(onDay(t, "2026-11-04")).toBe(true);
    expect(onDay({ ...t, excluded_days: ["2026-11-04"] }, "2026-11-04")).toBe(
      false,
    );
    expect(onDay({ ...t, included_days: ["2026-11-09"] }, "2026-11-09")).toBe(
      true,
    );
  });
  it("月历周一起始，跨月与跨年日期正确", () => {
    expect(monthCells("2026-11")).toHaveLength(42);
    expect(monthCells("2026-11")[0]).toBe("2026-10-26");
    expect(shiftDay("2026-12-31", 1)).toBe("2027-01-01");
  });
  it("完成项排在后面，不修改原集合", () => {
    const list = [
      task({ id: "done", completed: true }),
      task({ id: "pending" }),
    ];
    expect(sortTasks(list).map((t) => t.id)).toEqual(["pending", "done"]);
    expect(list[0].id).toBe("done");
  });
});
