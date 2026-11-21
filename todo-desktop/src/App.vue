<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import {
  CalendarDays,
  CalendarRange,
  CheckSquare,
  ChevronLeft,
  ChevronRight,
  LayoutList,
  Layers,
  Pencil,
  Plus,
  StickyNote,
  Tag,
} from "lucide-vue-next";
import { invoke } from "@tauri-apps/api/core";
import { app } from "./state";
import {
  bucketOf,
  bucketOrder,
  bucketTitles,
  dayLabel,
  doneOn,
  finishedOn,
  filterByLabels,
  monthCells,
  newDraft,
  priorityColor,
  shiftDay,
  shortDay,
  showsOn,
  sortBucket,
  sortTasks,
  weekdayShort,
} from "./domain";
import type { Task } from "./bindings/Task";
import TaskRows from "./components/TaskRows.vue";
import TaskEditor from "./components/TaskEditor.vue";
import ManageDialog from "./components/ManageDialog.vue";
import LabelFilter from "./components/LabelFilter.vue";
import Sticky from "./Sticky.vue";

const sticky = new URLSearchParams(location.search).get("view") === "sticky";

type View = "all" | "today" | "label";
const view = ref<View>("all");
const labelId = ref<string | null>(null);
const selected = ref(app.state.day);
const month = ref(app.state.day.slice(0, 7));
const search = ref("");
const hideDone = ref(false);
type Layout = "list" | "week" | "calendar";
const storedLayout = localStorage.getItem("task-notes-layout");
const layout = ref<Layout>(
  storedLayout === "calendar" || storedLayout === "week" ? storedLayout : "list",
);
function readLabelFilter(): string[] {
  try {
    const raw: unknown = JSON.parse(
      localStorage.getItem("task-notes-label-filter") ?? "[]",
    );
    return Array.isArray(raw) ? raw.filter((id): id is string => typeof id === "string") : [];
  } catch {
    return [];
  }
}

const weekOffset = ref(0);
const labelFilter = ref<string[]>(readLabelFilter());
watch(
  labelFilter,
  (value) => localStorage.setItem("task-notes-label-filter", JSON.stringify(value)),
  { deep: true },
);
const quick = ref("");
const quickInput = ref<HTMLInputElement>();
const autostart = ref(false);
const autostartBusy = ref(false);

/** 快速添加：回车即存为今天的事项，输入框清空并保持焦点，方便连着敲。 */
async function addQuick() {
  const title = quick.value.trim();
  if (!title || !app.state.ready || app.state.loading) return;
  const saved = await app.change({
    type: "task_save",
    id: null,
    draft: { ...newDraft(app.state.day), title },
  });
  if (saved) {
    quick.value = "";
    quickInput.value?.focus();
  }
}
async function toggleAutostart() {
  const target = autostart.value;
  autostartBusy.value = true;
  try {
    await invoke("set_autostart", { enabled: target });
  } catch {
    autostart.value = !target;
    app.state.error = "无法修改开机启动设置，请检查系统权限。";
  } finally {
    autostartBusy.value = false;
  }
}
const editing = ref(false);
const edited = ref<Task | null>(null);
const editingParent = ref<string | null>(null);
const editingStart = ref<string | null>(null);
const dialog = ref<{ kind: "project" | "section" | "label"; id: string | null; projectId: string | null } | null>(
  null,
);

const tasks = computed(() => app.snapshot.value.tasks);
const labels = computed(() => app.snapshot.value.labels);
const currentLabel = computed(
  () => labels.value.find((label) => label.id === labelId.value) ?? null,
);
const allCount = computed(() => tasks.value.filter((task) => !task.completed).length);
const todayCount = computed(
  () => tasks.value.filter((task) => showsOn(task, app.state.day) && !finishedOn(task, app.state.day)).length,
);

const scoped = computed<Task[]>(() => {
  if (view.value === "today") return tasks.value.filter((task) => showsOn(task, app.state.day));
  if (view.value === "label")
    return tasks.value.filter((task) => task.label_ids.includes(labelId.value ?? ""));
  return tasks.value;
});

const visible = computed(() => {
  const needle = search.value.trim().toLocaleLowerCase();
  return scoped.value.filter((task) => {
    if (hideDone.value && finishedOn(task, app.state.day)) return false;
    if (!needle) return true;
    const names = task.label_ids
      .map((id) => labels.value.find((label) => label.id === id)?.name ?? "")
      .join(" ");
    return `${task.title} ${task.notes} ${names}`.toLocaleLowerCase().includes(needle);
  });
});

const activeLabelFilter = computed(() =>
  labelFilter.value.filter((id) => labels.value.some((label) => label.id === id)),
);
/** 周 / 月布局额外按标签收敛，列表布局不受影响。 */
const layoutTasks = computed(() =>
  layout.value === "list"
    ? visible.value
    : filterByLabels(visible.value, activeLabelFilter.value),
);
function toggleLabel(id: string) {
  labelFilter.value = labelFilter.value.includes(id)
    ? labelFilter.value.filter((item) => item !== id)
    : [...labelFilter.value, id];
}

const groups = computed<Array<{ key: string; title: string; tasks: Task[] }>>(() => {
  if (!visible.value.length) return [];
  if (view.value === "today") return [{ key: "today", title: "今天", tasks: visible.value }];
  const buckets = new Map<string, Task[]>();
  for (const task of visible.value) {
    const key = bucketOf(task, app.state.day);
    const list = buckets.get(key);
    if (list) list.push(task);
    else buckets.set(key, [task]);
  }
  return bucketOrder
    .filter((key) => buckets.get(key)?.length)
    .map((key) => ({
      key,
      title: bucketTitles[key],
      tasks: sortBucket(buckets.get(key) ?? [], app.state.day),
    }));
});

const calendar = computed(
  () =>
    new Map(
      monthCells(month.value).map((day) => [
        day,
        sortTasks(layoutTasks.value.filter((task) => showsOn(task, day)), day),
      ]),
    ),
);
const selectedDayTasks = computed(() =>
  sortTasks(layoutTasks.value.filter((task) => showsOn(task, selected.value)), selected.value),
);
const weekDays = computed(() =>
  Array.from({ length: 7 }, (_, index) =>
    shiftDay(app.state.day, weekOffset.value + index),
  ),
);
const weekLabel = computed(() => {
  const days = weekDays.value;
  return `${shortDay(days[0])} – ${shortDay(days[6])}`;
});
const weekTasks = computed(
  () =>
    new Map(
      weekDays.value.map((day) => [
        day,
        sortTasks(layoutTasks.value.filter((task) => showsOn(task, day)), day),
      ]),
    ),
);

const listTitle = computed(() => {
  if (view.value === "today") return "今天";
  if (view.value === "label") return currentLabel.value?.name ?? "标签";
  return "所有事项";
});
const subtitle = computed(() => {
  if (view.value === "today") return `${dayLabel(app.state.day)} · 待办 ${todayCount.value} 项`;
  if (view.value === "label") return "按标签跨时间查看。";
  return `未完成 ${allCount.value} 项 · 按时间排`;
});
const emptyText = computed(() =>
  search.value
    ? "没有匹配的事项。"
    : view.value === "today"
      ? "今天还没有安排。"
      : "还没有事项。",
);

watch(layout, (value) => localStorage.setItem("task-notes-layout", value));

function open(next: View) {
  view.value = next;
  if (next !== "label") labelId.value = null;
}
function openLabel(id: string) {
  labelId.value = id;
  view.value = "label";
}
function createTask(start: string | null = null) {
  edited.value = null;
  editingParent.value = null;
  editingStart.value = start;
  editing.value = true;
}
function edit(task: Task | null = null) {
  if (!task) {
    createTask();
    return;
  }
  edited.value = task;
  editingParent.value = null;
  editingStart.value = null;
  editing.value = true;
}
function manageLabel(id: string | null = null) {
  dialog.value = { kind: "label", id, projectId: null };
}
function move(delta: number) {
  const date = new Date(month.value + "-15T12:00:00");
  date.setMonth(date.getMonth() + delta);
  month.value = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}
function goToday() {
  selected.value = app.state.day;
  month.value = app.state.day.slice(0, 7);
  open("today");
}
function choose(day: string) {
  selected.value = day;
  if (!day.startsWith(month.value)) month.value = day.slice(0, 7);
}
watch(
  () => app.state.day,
  (day, previous) => {
    if (selected.value === previous) {
      selected.value = day;
      month.value = day.slice(0, 7);
    }
  },
);
onMounted(async () => {
  void app.start();
  try {
    autostart.value = await invoke<boolean>("autostart_enabled");
  } catch {
    autostart.value = false;
  }
  await nextTick();
  quickInput.value?.focus();
});
onUnmounted(app.stop);
</script>

<template>
  <Sticky v-if="sticky" />
  <div v-else class="shell" :inert="editing || !!dialog">
    <aside class="sidebar">
      <div class="brand">
        <span class="brand-mark">✓</span><strong>事项便签</strong>
      </div>
      <nav aria-label="主导航">
        <button :class="{ active: view === 'all' }" @click="open('all')">
          <Layers :size="18" />所有事项<small>{{ allCount }}</small></button
        ><button :class="{ active: view === 'today' }" @click="open('today')">
          <CheckSquare :size="18" />今天<small>{{ todayCount }}</small>
        </button>
      </nav>

      <div class="nav-list" aria-label="标签">
        <header>
          <span>标签</span
          ><button class="quiet" aria-label="新建标签" @click="manageLabel()">
            <Plus :size="14" />
          </button>
        </header>
        <div
          v-for="label in labels"
          :key="label.id"
          class="nav-item"
          :class="{ active: view === 'label' && labelId === label.id }"
        >
          <button class="nav-main" @click="openLabel(label.id)">
            <Tag :size="13" :style="{ color: label.color }" />{{ label.name }}
          </button>
          <button
            class="edit"
            :aria-label="'编辑标签 ' + label.name"
            @click="manageLabel(label.id)"
          >
            <Pencil :size="12" />
          </button>
        </div>
        <p v-if="!labels.length" class="nav-empty">还没有标签</p>
      </div>

      <div class="sidebar-bottom">
        <button @click="app.action('show_sticky')">
          <StickyNote :size="18" />打开桌面便签</button
        ><small>仅显示今日待办<br />可置顶 · 可直接勾选</small>
        <label class="autostart-toggle">
          <input
            v-model="autostart"
            type="checkbox"
            :disabled="autostartBusy"
            @change="toggleAutostart"
          />开机自动启动
        </label>
      </div>
    </aside>

    <main>
      <header class="page-head">
        <div>
          <h1>{{ listTitle }}</h1>
          <p class="muted">{{ subtitle }}</p>
        </div>
        <div class="actions">
          <span v-if="view !== 'today'" class="layout-switch" role="group" aria-label="布局">
            <button
              :class="{ active: layout === 'list' }"
              aria-label="列表布局"
              :aria-pressed="layout === 'list'"
              @click="layout = 'list'"
            >
              <LayoutList :size="16" /></button
            ><button
              :class="{ active: layout === 'week' }"
              aria-label="七天布局"
              :aria-pressed="layout === 'week'"
              @click="layout = 'week'"
            >
              <CalendarRange :size="16" /></button
            ><button
              :class="{ active: layout === 'calendar' }"
              aria-label="月历布局"
              :aria-pressed="layout === 'calendar'"
              @click="layout = 'calendar'"
            >
              <CalendarDays :size="16" />
            </button>
          </span>
          <button @click="app.action('show_sticky')">
            <StickyNote :size="16" />便签</button
          ><button class="primary" :disabled="!app.state.ready" @click="createTask()">
            <Plus :size="17" />新增事项
          </button>
        </div>
      </header>

      <div v-if="app.state.error && !editing && !dialog" class="error-banner" role="alert">
        {{ app.state.error }} <button @click="app.refresh()">重试读取</button>
      </div>

      <form class="quick-add" @submit.prevent="addQuick">
        <input
          ref="quickInput"
          v-model="quick"
          type="text"
          aria-label="快速添加事项"
          placeholder="写点什么，回车就加进今天…"
          :disabled="!app.state.ready || app.state.loading"
          autocomplete="off"
          @keydown.esc="quick = ''"
        />
        <button
          class="primary"
          :disabled="!app.state.ready || app.state.loading || !quick.trim()"
        >
          添加
        </button>
      </form>

      <template v-if="layout === 'calendar' && view !== 'today'">
        <div class="toolbar">
          <button aria-label="上个月" @click="move(-1)">
            <ChevronLeft :size="16" /></button
          ><input
            type="month"
            v-model="month"
            aria-label="月份"
            min="1900-01"
            max="9999-12"
            @change="month ||= app.state.day.slice(0, 7)"
          /><button aria-label="下个月" @click="move(1)">
            <ChevronRight :size="16" /></button
          ><button @click="goToday">今天</button>
          <input
            v-model="search"
            type="search"
            aria-label="搜索事项"
            placeholder="搜索事项 / 备注 / 标签"
          /><label class="inline-label"
            ><input type="checkbox" v-model="hideDone" />隐藏已完成</label
          >
        </div>
        <LabelFilter
          :labels="labels"
          :selected="activeLabelFilter"
          @toggle="toggleLabel"
          @clear="labelFilter = []"
        />
        <div class="calendar-layout">
          <section class="panel calendar" aria-label="事项月历">
          <div class="weekday">
            <span v-for="d in ['一', '二', '三', '四', '五', '六', '日']" :key="d"
              >周{{ d }}</span
            >
          </div>
          <div class="month-grid">
            <button
              v-for="d in monthCells(month)"
              :key="d"
              class="day-cell"
              :class="{
                outside: !d.startsWith(month),
                current: d === app.state.day,
                selected: d === selected,
              }"
              :aria-label="d"
              :aria-pressed="d === selected"
              @click="choose(d)"
            >
              <span class="date-number">{{ Number(d.slice(-2)) }}</span
              ><span class="cell-tasks"
                ><span
                  v-for="t in calendar.get(d) ?? []"
                  :key="t.id"
                  class="calendar-task"
                  :class="{ done: doneOn(t, d) }"
                  :style="{ borderColor: t.color }"
                  >{{ t.title }}</span
                ></span
              >
            </button>
          </div>
        </section>
        <section class="panel day-panel" aria-label="当天安排">
          <header class="panel-head">
            <h2>
              {{ dayLabel(selected) }} 的安排
              <small class="muted">{{ selectedDayTasks.length }} 项</small>
            </h2>
          </header>
          <div class="list-scroll">
            <p v-if="!selectedDayTasks.length" class="empty">这一天没有安排。</p>
            <TaskRows v-else :tasks="selectedDayTasks" @edit="edit" />
          </div>
        </section>
        </div>
      </template>

      <template v-else-if="layout === 'week' && view !== 'today'">
        <div class="toolbar">
          <button aria-label="上一周" @click="weekOffset -= 7">
            <ChevronLeft :size="16" /></button
          ><span class="week-range">{{ weekLabel }}</span
          ><button aria-label="下一周" @click="weekOffset += 7">
            <ChevronRight :size="16" /></button
          ><button @click="weekOffset = 0">回到本周</button><span class="grow" />
          <input
            v-model="search"
            type="search"
            aria-label="搜索事项"
            placeholder="搜索事项 / 备注 / 标签"
          /><label class="inline-label"
            ><input type="checkbox" v-model="hideDone" />隐藏已完成</label
          >
        </div>
        <LabelFilter
          :labels="labels"
          :selected="activeLabelFilter"
          @toggle="toggleLabel"
          @clear="labelFilter = []"
        />
        <section class="panel week-panel" aria-label="七天安排">
          <div class="week-grid">
            <div
              v-for="day in weekDays"
              :key="day"
              class="week-column"
              :class="{ current: day === app.state.day }"
            >
              <header class="week-head">
                <span class="week-date">{{ shortDay(day) }}</span>
                <span class="week-weekday">周{{ weekdayShort(day) }}</span>
              </header>
              <div class="week-body">
                <button
                  v-for="task in weekTasks.get(day)"
                  :key="task.id"
                  class="week-task"
                  :class="{ done: doneOn(task, day) }"
                  :style="{ '--c': task.color }"
                  :title="task.title"
                  @click="edit(task)"
                >
                  <span
                    class="priority-bar"
                    :style="{ background: priorityColor(task.priority) }"
                  />
                  <span class="week-task-title">{{ task.title }}</span>
                </button>
                <p v-if="!(weekTasks.get(day)?.length)" class="week-empty">没有安排</p>
                <button
                  class="week-add"
                  :aria-label="'在 ' + day + ' 新增事项'"
                  @click="createTask(day)"
                >
                  ＋
                </button>
              </div>
            </div>
          </div>
        </section>
      </template>

      <section v-else class="panel list-panel expanded">
        <header class="panel-head">
          <h2>
            {{ listTitle }} <small class="muted">{{ visible.length }} 项</small>
          </h2>
          <div class="actions">
            <input
              v-model="search"
              type="search"
              aria-label="搜索事项"
              placeholder="搜索事项 / 备注 / 标签"
            /><label class="inline-label"
              ><input type="checkbox" v-model="hideDone" />隐藏已完成</label
            >
          </div>
        </header>
        <div class="list-scroll">
          <p v-if="!visible.length" class="empty">{{ emptyText }}</p>
          <template v-for="group in groups" :key="group.key">
            <p class="group-head">
              {{ group.title }}
              <small class="muted">{{ group.tasks.length }}</small>
            </p>
            <TaskRows
              :tasks="group.tasks"
              :today-actions="view === 'today'"
              :reorderable="view === 'today'"
              @edit="edit"
            />
          </template>
        </div>
      </section>

      <footer class="app-footer">
        <span>{{ app.state.ready ? "已保存到本机" : "正在读取…" }}</span
        ><span>新增默认今天 · 结束日期留空为单日 · {{ shortDay(app.state.day) }}</span>
      </footer>
    </main>
  </div>

  <TaskEditor
    v-if="!sticky"
    :open="editing"
    :task="edited"
    :parent-id="editingParent"
    :start-day="editingStart"
    @close="editing = false"
  />
  <ManageDialog
    v-if="!sticky && dialog"
    :open="!!dialog"
    :kind="dialog.kind"
    :id="dialog.id"
    :project-id="dialog.projectId"
    @close="dialog = null"
  />
</template>
