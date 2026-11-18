import { describe, expect, it } from "vitest";
import {
  dayLabel,
  monthCells,
  newDraft,
  onDay,
  orderedTree,
  parentOptions,
  shiftDay,
  sortTasks,
  today,
} from "../src/domain";
import type { Task } from "../src/bindings/Task";

const task = (overrides: Partial<Task> = {}): Task => ({
  ...newDraft("2026-11-04"),
  id: "one",
  position: 0,
  completed: false,
  completions: [],
  included_days: [],
  excluded_days: [],
  created_at: "2026-11-04T08:00:00+08:00",
  updated_at: "2026-11-04T08:00:00+08:00",
  ...overrides,
});

describe("独立事项的日期与完成显示", () => {
  it("新增始终默认本地今天、收件箱、无优先级", () => {
    const local = new Date(2026, 10, 4, 0, 5);
    expect(today(local)).toBe("2026-11-04");
    expect(newDraft().start).toBe(today());
    expect(newDraft().end).toBeNull();
    expect(newDraft().project_id).toBeNull();
    expect(newDraft().priority).toBe(4);
    expect(newDraft().label_ids).toEqual([]);
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
    expect(onDay(task({ start: null }), "2026-11-04")).toBe(false);
  });

  it("月历周一起始，跨月与跨年日期正确", () => {
    expect(monthCells("2026-11")).toHaveLength(42);
    expect(monthCells("2026-11")[0]).toBe("2026-10-26");
    expect(shiftDay("2026-12-31", 1)).toBe("2027-01-01");
    expect(dayLabel("2026-11-04")).toBe("11月4日 周三");
  });

  it("完成项排在后面，按手动顺序排列，不修改原集合", () => {
    const list = [
      task({ id: "done", completed: true, position: 1 }),
      task({ id: "second", position: 2 }),
      task({ id: "first", position: 1 }),
    ];
    expect(sortTasks(list).map((t) => t.id)).toEqual(["first", "second", "done"]);
    expect(list[0].id).toBe("done");
  });
});

describe("项目、标签与子事项", () => {
  it("子事项紧跟在父事项后面并带层级", () => {
    const parent = task({ id: "p", position: 1 });
    const child = task({ id: "c", position: 5, parent_id: "p" });
    const other = task({ id: "o", position: 2 });
    const rows = orderedTree([child, other, parent]);
    expect(rows.map((row) => [row.task.id, row.depth])).toEqual([
      ["p", 0],
      ["c", 1],
      ["o", 0],
    ]);
  });

  it("父事项缺失时子事项按顶层显示，不会丢失", () => {
    const orphan = task({ id: "c", parent_id: "missing" });
    expect(orderedTree([orphan])).toEqual([{ task: orphan, depth: 0 }]);
  });

  it("选择父事项时排除自己与自己的后代", () => {
    const parent = task({ id: "p", position: 1 });
    const child = task({ id: "c", position: 2, parent_id: "p" });
    const grandchild = task({ id: "g", position: 3, parent_id: "c" });
    const legacy = task({ id: "x", position: 4 });
    expect(parentOptions([parent, child, grandchild, legacy], "p").map((t) => t.id)).toEqual(["x"]);
    expect(parentOptions([parent, child, legacy], null).map((t) => t.id)).toEqual([
      "p",
      "c",
      "x",
    ]);
  });
});
