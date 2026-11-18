<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import {
  CalendarDays,
  CalendarRange,
  CheckSquare,
  ChevronLeft,
  ChevronRight,
  Inbox,
  Layers,
  Pencil,
  Plus,
  StickyNote,
  Tag,
} from "lucide-vue-next";
import { app } from "./state";
import { dayLabel, monthCells, onDay, shiftDay, shortDay } from "./domain";
import type { Task } from "./bindings/Task";
import TaskRows from "./components/TaskRows.vue";
import TaskEditor from "./components/TaskEditor.vue";
import ManageDialog from "./components/ManageDialog.vue";
import Sticky from "./Sticky.vue";

const sticky = new URLSearchParams(location.search).get("view") === "sticky";

type View = "inbox" | "today" | "upcoming" | "calendar" | "all" | "project" | "label";
const view = ref<View>("today");
const projectId = ref<string | null>(null);
const labelId = ref<string | null>(null);
const selected = ref(app.state.day);
const month = ref(app.state.day.slice(0, 7));
const search = ref("");
const hideDone = ref(false);
const editing = ref(false);
const edited = ref<Task | null>(null);
const editingProject = ref<string | null>(null);
const editingParent = ref<string | null>(null);
const dialog = ref<{
  kind: "project" | "section" | "label";
  id: string | null;
  projectId: string | null;
} | null>(null);

const tasks = computed(() => app.snapshot.value.tasks);
const projects = computed(() => app.snapshot.value.projects);
const labels = computed(() => app.snapshot.value.labels);
const orderedProjects = computed(() =>
  [...projects.value].sort(
    (a, b) => Number(b.favorite) - Number(a.favorite) || a.position - b.position,
  ),
);
const currentProject = computed(
  () => projects.value.find((project) => project.id === projectId.value) ?? null,
);
const currentLabel = computed(
  () => labels.value.find((label) => label.id === labelId.value) ?? null,
);
const sections = computed(() =>
  app.snapshot.value.sections.filter(
    (section) => section.project_id === projectId.value,
  ),
);

const todayLeft = computed(
  () => tasks.value.filter((t) => onDay(t, app.state.day) && !t.completed).length,
);
const inboxCount = computed(
  () =>
    tasks.value.filter((t) => t.project_id === null && !t.completed).length,
);

function overlaps(task: Task, from: string, to: string) {
  const start = task.start ?? task.end;
  if (!start) return false;
  const end = task.end ?? start;
  return start <= to && end >= from;
}

const scoped = computed<Task[]>(() => {
  switch (view.value) {
    case "inbox":
      return tasks.value.filter((task) => task.project_id === null);
    case "today":
      return tasks.value.filter((task) => onDay(task, app.state.day));
    case "upcoming": {
      const last = shiftDay(app.state.day, 6);
      return tasks.value.filter((task) => overlaps(task, app.state.day, last));
    }
    case "calendar":
      return tasks.value.filter((task) => onDay(task, selected.value));
    case "project":
      return tasks.value.filter((task) => task.project_id === projectId.value);
    case "label":
      return tasks.value.filter((task) =>
        task.label_ids.includes(labelId.value ?? ""),
      );
    default:
      return tasks.value;
  }
});

const visible = computed(() => {
  const needle = search.value.trim().toLocaleLowerCase();
  return scoped.value.filter((task) => {
    if (hideDone.value && task.completed) return false;
    if (!needle) return true;
    const names = task.label_ids
      .map((id) => labels.value.find((label) => label.id === id)?.name ?? "")
      .join(" ");
    const project = projects.value.find((item) => item.id === task.project_id);
    return `${task.title} ${task.notes} ${names} ${project?.name ?? ""}`
      .toLocaleLowerCase()
      .includes(needle);
  });
});

const groups = computed<Array<{ key: string; title: string | null; tasks: Task[] }>>(() => {
  if (!visible.value.length) return [];
  if (view.value === "upcoming") {
    return Array.from({ length: 7 }, (_, index) => {
      const day = shiftDay(app.state.day, index);
      return {
        key: day,
        title:
          index === 0
            ? `今天 · ${dayLabel(day)}`
            : `${dayLabel(day)} · ${shortDay(day)}`,
        tasks: visible.value.filter((task) => onDay(task, day)),
      };
    }).filter((group) => group.tasks.length);
  }
  if (view.value === "project" && sections.value.length) {
    const unsectioned = visible.value.filter((task) => !task.section_id);
    return [
      ...(unsectioned.length
        ? [{ key: "none", title: "未分区", tasks: unsectioned }]
        : []),
      ...sections.value
        .map((section) => ({
          key: section.id,
          title: section.name,
          tasks: visible.value.filter((task) => task.section_id === section.id),
        }))
        .filter((group) => group.tasks.length),
    ];
  }
  return [{ key: "all", title: null, tasks: visible.value }];
});

const calendar = computed(
  () =>
    new Map(
      monthCells(month.value).map((day) => [
        day,
        tasks.value.filter((task) => onDay(task, day)),
      ]),
    ),
);

const listTitle = computed(() => {
  switch (view.value) {
    case "inbox":
      return "收件箱";
    case "today":
      return "今天";
    case "upcoming":
      return "接下来 7 天";
    case "calendar":
      return `${dayLabel(selected.value)} 的安排`;
    case "project":
      return currentProject.value?.name ?? "项目";
    case "label":
      return currentLabel.value?.name ?? "标签";
    default:
      return "全部事项";
  }
});

const subtitle = computed(() => {
  switch (view.value) {
    case "inbox":
      return "还没归到项目里的事项。";
    case "today":
      return `${dayLabel(app.state.day)} · 待办 ${todayLeft.value} 项`;
    case "upcoming":
      return "未来七天，按天排开。";
    case "calendar":
      return "按月查看，点一天看当天安排。";
    case "project":
      return sections.value.length
        ? `${sections.value.length} 个分区`
        : "还没有分区，可按阶段拆分。";
    case "label":
      return "跨项目按标签查看。";
    default:
      return `${tasks.value.length} 条事项`;
  }
});

const emptyText = computed(() =>
  search.value
    ? "没有匹配的事项。"
    : view.value === "today"
      ? "今天还没有安排。"
      : "这一栏是空的。",
);

function open(next: View) {
  view.value = next;
  if (next !== "project") projectId.value = null;
  if (next !== "label") labelId.value = null;
}
function openProject(id: string) {
  projectId.value = id;
  view.value = "project";
  labelId.value = null;
}
function openLabel(id: string) {
  labelId.value = id;
  view.value = "label";
  projectId.value = null;
}
function createTask(parentId: string | null = null) {
  edited.value = null;
  editingProject.value = view.value === "project" ? projectId.value : null;
  editingParent.value = parentId;
  editing.value = true;
}
function edit(task: Task | null = null) {
  if (!task) {
    createTask();
    return;
  }
  edited.value = task;
  editingProject.value = task.project_id;
  editingParent.value = null;
  editing.value = true;
}
function manage(
  kind: "project" | "section" | "label",
  id: string | null = null,
  project: string | null = null,
) {
  dialog.value = { kind, id, projectId: project };
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
  view.value = "calendar";
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
onMounted(() => void app.start());
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
        <button :class="{ active: view === 'inbox' }" @click="open('inbox')">
          <Inbox :size="18" />收件箱<small>{{ inboxCount }}</small></button
        ><button :class="{ active: view === 'today' }" @click="open('today')">
          <CheckSquare :size="18" />今天<small>{{ todayLeft }}</small></button
        ><button
          :class="{ active: view === 'upcoming' }"
          @click="open('upcoming')"
        >
          <CalendarRange :size="18" />接下来</button
        ><button
          :class="{ active: view === 'calendar' }"
          @click="open('calendar')"
        >
          <CalendarDays :size="18" />月历</button
        ><button :class="{ active: view === 'all' }" @click="open('all')">
          <Layers :size="18" />全部事项
        </button>
      </nav>

      <div class="nav-list" aria-label="项目">
        <header>
          <span>项目</span
          ><button class="quiet" aria-label="新建项目" @click="manage('project')">
            <Plus :size="14" />
          </button>
        </header>
        <div
          v-for="project in orderedProjects"
          :key="project.id"
          class="nav-item"
          :class="{ active: view === 'project' && projectId === project.id }"
        >
          <button class="nav-main" @click="openProject(project.id)">
            <span class="dot" :style="{ background: project.color }" />{{
              project.name
            }}
          </button>
          <button
            class="edit"
            :aria-label="'编辑项目 ' + project.name"
            @click="manage('project', project.id)"
          >
            <Pencil :size="12" />
          </button>
        </div>
        <p v-if="!projects.length" class="nav-empty">还没有项目</p>
      </div>

      <div class="nav-list" aria-label="标签">
        <header>
          <span>标签</span
          ><button class="quiet" aria-label="新建标签" @click="manage('label')">
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
            @click="manage('label', label.id)"
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
      </div>
    </aside>

    <main>
      <header class="page-head">
        <div>
          <h1>{{ listTitle }}</h1>
          <p class="muted">{{ subtitle }}</p>
        </div>
        <div class="actions">
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

      <template v-if="view === 'calendar'">
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
          ><button @click="goToday">今天</button><span class="grow" />
        </div>
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
              ><span
                v-for="t in calendar.get(d)?.slice(0, 3)"
                :key="t.id"
                class="calendar-task"
                :class="{ done: t.completed }"
                :style="{ borderColor: t.color }"
                >{{ t.title }}</span
              ><small v-if="(calendar.get(d)?.length ?? 0) > 3" class="muted"
                >另 {{ (calendar.get(d)?.length ?? 0) - 3 }} 项</small
              >
            </button>
          </div>
        </section>
      </template>

      <section class="panel list-panel" :class="{ expanded: view !== 'calendar' }">
        <header class="panel-head">
          <h2>
            {{ view === "calendar" ? dayLabel(selected) + " 的安排" : listTitle }}
            <small class="muted">{{ visible.length }} 项</small>
          </h2>
          <div class="actions">
            <button
              v-if="view === 'project' && currentProject"
              @click="manage('section', null, currentProject.id)"
            >
              新建分区
            </button>
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
            <p v-if="group.title" class="group-head">
              {{ group.title }}
              <small class="muted">{{ group.tasks.length }}</small>
            </p>
            <TaskRows
              :tasks="group.tasks"
              :today-actions="view === 'today'"
              :show-project="view === 'label' || view === 'all' || view === 'upcoming'"
              :reorderable="view !== 'upcoming'"
              @edit="edit"
            />
          </template>
        </div>
      </section>

      <footer class="app-footer">
        <span>{{ app.state.ready ? "已保存到本机" : "正在读取…" }}</span
        ><span>新增默认今天 · 结束日期留空为单日 · 可拖拽排序</span>
      </footer>
    </main>
  </div>

  <TaskEditor
    v-if="!sticky"
    :open="editing"
    :task="edited"
    :project-id="editingProject"
    :parent-id="editingParent"
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
