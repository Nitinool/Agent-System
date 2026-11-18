// Real WebView2 → Tauri → SQLite, in a disposable LOCALAPPDATA profile.
import { chromium, expect } from "@playwright/test";
import { spawn } from "node:child_process";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { resolve, join } from "node:path";
import net from "node:net";
const root = resolve(import.meta.dirname, "..");
const binary = resolve(
  process.argv[2] || join(root, "bin/task-notes.exe"),
);
await mkdir(join(root, ".test-data"), { recursive: true });
const profile = await mkdtemp(join(root, ".test-data/native-"));
const errors = [];
let child, browser, main, sticky;
async function freePort() {
  return new Promise((resolve) => {
    const s = net.createServer();
    s.listen(0, "127.0.0.1", () => {
      const port = s.address().port;
      s.close(() => resolve(port));
    });
  });
}
async function start() {
  const port = await freePort();
  child = spawn(binary, [], {
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
    env: {
      ...process.env,
      LOCALAPPDATA: profile,
      WEBVIEW2_USER_DATA_FOLDER: join(profile, "webview"),
      WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: `--remote-debugging-port=${port} --remote-debugging-address=127.0.0.1`,
    },
  });
  child.on("error", (e) => errors.push(e.message));
  child.stderr.on("data", () => {});
  child.stdout.on("data", () => {});
  let ready = false;
  for (let i = 0; i < 150; i++) {
    if (child.exitCode !== null)
      throw Error("Process exited: " + child.exitCode);
    try {
      if ((await fetch(`http://127.0.0.1:${port}/json/version`)).ok) {
        ready = true;
        break;
      }
    } catch {}
    await new Promise((r) => setTimeout(r, 200));
  }
  if (!ready) throw Error("WebView2 did not start");
  browser = await chromium.connectOverCDP(`http://127.0.0.1:${port}`);
  await expect
    .poll(
      () =>
        browser
          .contexts()
          .flatMap((c) => c.pages())
          .filter((p) => !p.url().startsWith("about:")).length,
    )
    .toBe(2);
  const pages = browser.contexts().flatMap((c) => c.pages());
  main = pages.find(
    (p) => !p.url().includes("view=sticky") && !p.url().startsWith("about:"),
  );
  sticky = pages.find((p) => p.url().includes("view=sticky"));
  for (const page of [main, sticky])
    page.on("pageerror", (e) => errors.push(e.message));
  try {
    await expect(
      main.getByRole("button", { name: "新增事项", exact: true }),
    ).toBeEnabled({ timeout: 15000 });
  } catch (error) {
    console.error("Startup page:", await main.locator("body").innerText());
    console.error(
      "Startup IPC:",
      await main.evaluate(async () => {
        try {
          return await window.__TAURI_INTERNALS__.invoke("snapshot");
        } catch (error) {
          return { error };
        }
      }),
    );
    throw error;
  }
}
async function ipc(page, command, args = {}) {
  return page.evaluate(
    ({ command, args }) => window.__TAURI_INTERNALS__.invoke(command, args),
    { command, args },
  );
}
async function exit() {
  if (child?.exitCode === null) {
    const exited = new Promise((resolve) => child.once("exit", resolve));
    try {
      await ipc(main, "quit_app");
    } catch {}
    let timeout;
    try {
      await Promise.race([
        exited,
        new Promise((_, reject) => {
          timeout = setTimeout(() => reject(Error("Shutdown timeout")), 10000);
        }),
      ]);
    } finally {
      clearTimeout(timeout);
    }
  }
  try {
    await browser?.close();
  } catch {}
}
function findTask(snapshot, title) {
  return snapshot.tasks.find((t) => t.title === title);
}
try {
  await start();
  expect((await ipc(main, "snapshot")).tasks).toEqual([]);
  const day = await main.evaluate(() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  });
  const tomorrow = await main.evaluate((day) => {
    const d = new Date(day + "T12:00:00");
    d.setDate(d.getDate() + 1);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }, day);
  await main.getByRole("button", { name: "新增事项", exact: true }).click();
  await expect(main.getByLabel("开始日期", { exact: true })).toHaveValue(day);
  await expect(main.getByLabel("结束日期", { exact: true })).toHaveValue("");
  await main.getByLabel("事项名称", { exact: true }).fill("独立应用联动事项");
  await main.getByLabel("备注", { exact: true }).fill("备注重启后保留");
  await main.getByRole("button", { name: "保存", exact: true }).click();
  await main.getByRole("button", { name: "便签", exact: true }).click();
  await expect(
    sticky.getByRole("checkbox", { name: "完成 独立应用联动事项" }),
  ).toBeVisible();
  await sticky.getByRole("checkbox", { name: "完成 独立应用联动事项" }).check();
  await expect(
    main.getByRole("checkbox", { name: "完成 独立应用联动事项" }),
  ).toBeChecked();
  await expect(
    sticky.locator(".task-row").filter({ hasText: "独立应用联动事项" }),
  ).toHaveClass(/done/);
  await main.getByRole("checkbox", { name: "完成 独立应用联动事项" }).uncheck();
  await expect(
    sticky.getByRole("checkbox", { name: "完成 独立应用联动事项" }),
  ).not.toBeChecked();
  let snap = await ipc(main, "snapshot"),
    task = findTask(snap, "独立应用联动事项");
  expect(task.completions).toHaveLength(1);
  expect(task.completions[0].reopened_at).toBeTruthy();
  const yesterday = await main.evaluate((day) => {
    const d = new Date(day + "T12:00:00");
    d.setDate(d.getDate() - 1);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }, day);
  const add = async (title, start, end = null) => {
    snap = await ipc(main, "snapshot");
    await ipc(main, "mutate", {
      revision: snap.revision,
      mutation: {
        type: "task_save",
        id: null,
        draft: {
          title,
          notes: "",
          color: "#8b5cf6",
          priority: 4,
          start,
          end,
          project_id: null,
          section_id: null,
          parent_id: null,
          label_ids: [],
        },
      },
    });
  };
  await add("明天才做", tomorrow);
  await add("没有安排", null);
  await add("范围内每天出现", yesterday, tomorrow);
  await expect(sticky.getByRole("checkbox")).toHaveCount(2);
  await expect(sticky.getByText("明天才做")).toHaveCount(0);
  await expect(sticky.getByText("没有安排")).toHaveCount(0);
  await sticky.getByRole("button", { name: "取消置顶" }).click();
  await expect(
    sticky.getByRole("button", { name: "置顶便签" }),
  ).toHaveAttribute("aria-pressed", "false");
  await sticky.getByRole("button", { name: "置顶便签" }).click();
  await expect(
    sticky.getByRole("button", { name: "取消置顶" }),
  ).toHaveAttribute("aria-pressed", "true");
  await main.getByRole("button", { name: "月历布局" }).click();
  await expect(main.locator(".calendar")).toBeVisible();
  await main.screenshot({ path: join(profile, "calendar.png") });
  // Native WebView editor focus and default date, after selecting tomorrow.
  await main.getByLabel(tomorrow, { exact: true }).click();
  await main.getByRole("button", { name: "新增事项", exact: true }).click();
  await expect(main.getByLabel("开始日期", { exact: true })).toHaveValue(day);
  await main.getByLabel("事项名称", { exact: true }).fill("保留编辑草稿");
  await main.getByRole("button", { name: "取消", exact: true }).click();
  await expect(main.getByRole("button", { name: "继续编辑" })).toBeVisible();
  await main.getByRole("button", { name: "继续编辑" }).click();
  await expect(main.getByLabel("事项名称", { exact: true })).toHaveValue(
    "保留编辑草稿",
  );
  await main.getByRole("button", { name: "取消", exact: true }).click();
  await main.getByRole("button", { name: "放弃修改" }).click();
  await main.getByRole("button", { name: "列表布局" }).click();
  await main.locator(".sidebar").getByRole("button", { name: "今天" }).click();
  await main.getByRole("button", { name: "移出今天 独立应用联动事项" }).click();
  await expect(
    sticky.getByText("独立应用联动事项", { exact: true }),
  ).toHaveCount(0);
  await main.locator(".sidebar").getByRole("button", { name: "所有事项" }).click();
  await main.getByRole("button", { name: "加入今天 独立应用联动事项" }).click();
  await expect(
    sticky.getByText("独立应用联动事项", { exact: true }),
  ).toBeVisible();
  await main.locator(".sidebar").getByRole("button", { name: "今天" }).click();
  await main.screenshot({ path: join(profile, "main.png") });
  await sticky.screenshot({ path: join(profile, "sticky.png") });
  snap = await ipc(main, "snapshot");
  // A simultaneous stale mutation must fail without writing.
  const rejected = await sticky.evaluate(
    async (args) => {
      try {
        await window.__TAURI_INTERNALS__.invoke("mutate", args);
        return null;
      } catch (error) {
        return error;
      }
    },
    { revision: snap.revision - 1, mutation: { type: "task_delete", id: task.id } },
  );
  expect(rejected.code).toBe("stale");
  // Midnight switches the sticky list without a restart. Preserve system date.
  await sticky.clock.install({ time: new Date(day + "T23:59:59") });
  await sticky.clock.fastForward(2000);
  await expect(sticky.getByText(tomorrow, { exact: true })).toBeVisible();
  await expect(sticky.getByText("明天才做", { exact: true })).toBeVisible();
  await expect(
    sticky.getByText("独立应用联动事项", { exact: true }),
  ).toHaveCount(0);
  await exit();
  await start();
  const restarted = await ipc(main, "snapshot");
  expect(restarted).toEqual(snap);
  expect(findTask(restarted, "独立应用联动事项").notes).toBe("备注重启后保留");
  await main.getByRole("button", { name: "便签", exact: true }).click();
  await expect(
    sticky.getByText("独立应用联动事项", { exact: true }),
  ).toBeVisible();
  // Actual editor deletion propagates to both windows.
  await main
    .locator(".task-row")
    .filter({ hasText: "独立应用联动事项" })
    .first()
    .locator(".task-title")
    .click();
  await main.getByRole("button", { name: "删除事项", exact: true }).click();
  await main.getByRole("button", { name: "确认删除", exact: true }).click();
  await expect(
    sticky.getByText("独立应用联动事项", { exact: true }),
  ).toHaveCount(0);
  expect((await ipc(main, "snapshot")).tasks).toHaveLength(3);

  // ---- 标签 / 优先级 / 子事项 / 时间分组 / 布局切换 ----
  await main.locator(".sidebar").getByRole("button", { name: "新建标签" }).click();
  await main.getByLabel("标签名称").fill("紧急");
  await main.getByRole("button", { name: "保存", exact: true }).click();
  await expect(main.locator(".nav-item").filter({ hasText: "紧急" })).toBeVisible();

  await main.locator(".sidebar").getByRole("button", { name: "所有事项" }).click();
  await main.getByRole("button", { name: "新增事项", exact: true }).click();
  await main.getByLabel("事项名称", { exact: true }).fill("写方案");
  await main.locator(".priority-option").first().click();
  await main.locator(".chip-input").filter({ hasText: "紧急" }).click();
  await main.getByRole("button", { name: "保存", exact: true }).click();

  snap = await ipc(main, "snapshot");
  const plan = findTask(snap, "写方案");
  expect(plan.priority).toBe(1);
  expect(plan.label_ids).toHaveLength(1);
  expect(plan.project_id).toBe(null);

  await main.getByRole("button", { name: "新增事项", exact: true }).click();
  await main.getByLabel("事项名称", { exact: true }).fill("拆解步骤");
  await main.getByLabel("父事项").selectOption({ label: "写方案" });
  await main.getByRole("button", { name: "保存", exact: true }).click();
  snap = await ipc(main, "snapshot");
  const step = findTask(snap, "拆解步骤");
  expect(step.parent_id).toBe(plan.id);
  await expect(main.locator(".task-row.subtask")).toHaveCount(1);

  // 所有事项按时间分组：今天桶里应有写方案与它的子事项。
  const todayGroup = main.locator(".list-scroll").locator(".group-head").filter({ hasText: "今天" });
  await expect(todayGroup).toBeVisible();

  // 标签视图可以跨项目/跨时间收敛
  await main.locator(".nav-item").filter({ hasText: "紧急" }).locator(".nav-main").click();
  await expect(
    main.locator(".task-row").filter({ hasText: "写方案" }),
  ).toBeVisible();

  // 布局切换记住并切回
  await main.getByRole("button", { name: "月历布局" }).click();
  await expect(main.locator(".calendar")).toBeVisible();
  await main.getByRole("button", { name: "列表布局" }).click();
  await expect(main.locator(".calendar")).toHaveCount(0);

  expect(errors).toEqual([]);
  console.log(
    JSON.stringify(
      {
        passed: true,
        profile,
        checks: [
          "default-today",
          "single-day",
          "cross-window-complete-reopen",
          "date-range",
          "sticky-today-only",
          "pin",
          "draft-retention",
          "remove-and-readd-today",
          "stale-write",
          "midnight",
          "restart",
          "delete",
          "label-create",
          "priority",
          "subtask",
          "time-buckets",
          "layout-switch",
        ],
        errors,
      },
      null,
      2,
    ),
  );
} finally {
  await exit();
  await writeFile(
    join(profile, "errors.json"),
    JSON.stringify(errors, null, 2),
  );
}
