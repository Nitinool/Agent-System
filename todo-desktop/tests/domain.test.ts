import { describe, expect, it } from "vitest";
import {
  bucketOf,
  dayLabel,
  doneOn,
  filterByLabels,
  finishedOn,
  monthCells,
  newDraft,
  occursOn,
  onDay,
  orderedTree,
  parentOptions,
  shiftDay,
  showsOn,
  sortBucket,
  sortTasks,
  today,
  weekdayShort,
} from "../src/domain";
import type { Task } from "../src/bindings/Task";

const task = (overrides: Partial<Task> = {}): Task => ({
  ...newDraft("2026-11-04"),
  id: "one",
  position: 0,
  completed: false,
  completions: [],
  deleted_at: null,
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

  it("月历周一起始，跨月与跨年日期正确，五周的月份只渲染五行", () => {
    expect(monthCells("2026-11")).toHaveLength(42);
    expect(monthCells("2026-11")[0]).toBe("2026-10-26");
    expect(monthCells("2026-06")).toHaveLength(35);
    expect(shiftDay("2026-12-31", 1)).toBe("2027-01-01");
    expect(dayLabel("2026-11-04")).toBe("11月4日 周三");
    expect(weekdayShort("2026-11-04")).toBe("三");
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

describe("所有事项的时间分组", () => {
  const day = "2026-11-18";

  it("按今天、明天、本周、以后、待安排、已过期归桶，每条只归一个", () => {
    expect(bucketOf(task({ start: null, end: null }), day)).toBe("none");
    expect(bucketOf(task({ start: "2026-11-10", end: "2026-11-10" }), day)).toBe("overdue");
    expect(bucketOf(task({ start: day, end: null }), day)).toBe("today");
    expect(bucketOf(task({ start: "2026-11-17", end: "2026-11-20" }), day)).toBe("today");
    expect(bucketOf(task({ start: "2026-11-19", end: null }), day)).toBe("tomorrow");
    expect(bucketOf(task({ start: "2026-11-21", end: null }), day)).toBe("week");
    expect(bucketOf(task({ start: "2026-12-30", end: null }), day)).toBe("later");
  });

  it("范围已经走完才算过期，跨今天的不算", () => {
    expect(bucketOf(task({ start: "2026-11-01", end: "2026-11-17" }), day)).toBe("overdue");
    expect(bucketOf(task({ start: "2026-11-01", end: "2026-11-18" }), day)).toBe("today");
  });

  it("显式移出今天的事项不再进今天桶", () => {
    const moved = task({ start: day, end: day, excluded_days: [day] });
    expect(bucketOf(moved, day)).not.toBe("today");
  });

  it("同一个桶里按开始日期排，无日期的沉底，同日期保持手动顺序", () => {    const list = [
      task({ id: "none", start: null, position: 1 }),
      task({ id: "late", start: "2026-12-20", position: 2 }),
      task({ id: "early", start: "2026-12-01", position: 3 }),
      task({ id: "same-b", start: "2026-12-01", position: 9 }),
    ];
    expect(sortBucket(list).map((t) => t.id)).toEqual([
      "early",
      "same-b",
      "late",
      "none",
    ]);
  });
});

describe("标签筛选", () => {
  const a = task({ id: "a", label_ids: ["x"] });
  const b = task({ id: "b", label_ids: ["y"] });
  const c = task({ id: "c", label_ids: [] });
  const both = task({ id: "d", label_ids: ["x", "y"] });

  it("不选标签时返回全部，包含没有标签的事项", () => {
    expect(filterByLabels([a, b, c, both], []).map((t) => t.id)).toEqual([
      "a",
      "b",
      "c",
      "d",
    ]);
  });

  it("勾一个标签只留命中的，勾多个是并集", () => {
    expect(filterByLabels([a, b, c, both], ["x"]).map((t) => t.id)).toEqual(["a", "d"]);
    expect(filterByLabels([a, b, c, both], ["x", "y"]).map((t) => t.id)).toEqual([
      "a",
      "b",
      "d",
    ]);
    expect(filterByLabels([a, b, c, both], ["z"])).toEqual([]);
  });
});

describe("重复事项", () => {
  it("每天：开始日期起每天命中，重复截止之后不再命中", () => {
    const t = task({ start: "2026-11-18", end: null, recurrence: "daily" });
    expect(occursOn(t, "2026-11-17")).toBe(false);
    expect(occursOn(t, "2026-11-18")).toBe(true);
    expect(occursOn(t, "2026-12-31")).toBe(true);
    expect(occursOn({ ...t, repeat_until: "2026-11-20" }, "2026-11-20")).toBe(true);
    expect(occursOn({ ...t, repeat_until: "2026-11-20" }, "2026-11-21")).toBe(false);
  });

  it("每隔三天：只看与锚点对齐的日子", () => {
    const t = task({ start: "2026-11-18", end: null, recurrence: "every:3" });
    expect(occursOn(t, "2026-11-19")).toBe(false);
    expect(occursOn(t, "2026-11-21")).toBe(true);
    expect(occursOn(t, "2026-11-24")).toBe(true);
  });

  it("勾完当天后日期已滚到下一次，但当天仍显示为已完成", () => {
    const rolled = task({
      start: "2026-11-19",
      recurrence: "daily",
      completions: [
        {
          completed_at: "2026-11-18T09:00:00+08:00",
          reopened_at: null,
          due_date: "2026-11-18",
        },
      ],
    });
    expect(occursOn(rolled, "2026-11-18")).toBe(false);
    expect(doneOn(rolled, "2026-11-18")).toBe(true);
    expect(showsOn(rolled, "2026-11-18")).toBe(true);
    expect(doneOn(rolled, "2026-11-19")).toBe(false);
    expect(showsOn(rolled, "2026-11-19")).toBe(true);
    expect(bucketOf(rolled, "2026-11-18")).toBe("today");
  });

  it("撤销过的完成记录不再算完成", () => {
    const reopened = task({
      start: "2026-11-18",
      recurrence: "daily",
      completions: [
        {
          completed_at: "2026-11-18T09:00:00+08:00",
          reopened_at: "2026-11-18T10:00:00+08:00",
          due_date: "2026-11-18",
        },
      ],
    });
    expect(doneOn(reopened, "2026-11-18")).toBe(false);
  });

  it("勾掉的重复事项排到最后，第二天又回到正常位置", () => {
    const done = task({
      id: "done",
      position: 1,
      recurrence: "daily",
      completions: [
        {
          completed_at: "2026-11-18T09:00:00+08:00",
          reopened_at: null,
          due_date: "2026-11-18",
        },
      ],
    });
    const open = task({ id: "open", position: 2 });
    expect(sortTasks([done, open], "2026-11-18").map((t) => t.id)).toEqual([
      "open",
      "done",
    ]);
    expect(sortTasks([done, open], "2026-11-19").map((t) => t.id)).toEqual([
      "done",
      "open",
    ]);
  });
});

describe("完成态的日期边界", () => {
  it("普通事项勾掉后只在自己的安排日显示，不会铺满整月", () => {
    const t = task({ start: "2026-11-19", end: "2026-11-20", completed: true });
    expect(doneOn(t, "2026-11-19")).toBe(true);
    expect(doneOn(t, "2026-11-21")).toBe(false);
    expect(showsOn(t, "2026-11-19")).toBe(true);
    expect(showsOn(t, "2026-11-21")).toBe(false);
    expect(showsOn(t, "2026-11-01")).toBe(false);
    expect(finishedOn(t, "2026-11-21")).toBe(true);
  });

  it("没有日期的已完成事项不会出现在任何一天", () => {
    const t = task({ start: null, end: null, completed: true });
    expect(showsOn(t, "2026-11-19")).toBe(false);
    expect(finishedOn(t, "2026-11-19")).toBe(true);
  });
});

describe("子事项", () => {
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
