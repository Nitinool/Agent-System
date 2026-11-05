<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import {
  CalendarDays,
  CheckSquare,
  StickyNote,
  Plus,
  ChevronLeft,
  ChevronRight,
} from "lucide-vue-next";
import { app } from "./state";
import { monthCells, onDay, sortTasks } from "./domain";
import type { Task } from "./bindings/Task";
import TaskRows from "./components/TaskRows.vue";
import TaskEditor from "./components/TaskEditor.vue";
import Sticky from "./Sticky.vue";
const sticky = new URLSearchParams(location.search).get("view") === "sticky";
const view = ref<"calendar" | "today">("calendar"),
  selected = ref(app.state.day),
  month = ref(app.state.day.slice(0, 7));
const filter = ref<"day" | "unscheduled" | "all">("day"),
  search = ref(""),
  hideDone = ref(false);
const editing = ref(false),
  editedTask = ref<Task | null>(null);
const cells = computed(() => monthCells(month.value));
const calendar = computed(
  () =>
    new Map(
      cells.value.map((day) => [
        day,
        sortTasks(app.snapshot.value.tasks.filter((t) => onDay(t, day))),
      ]),
    ),
);
const todayCompleted = computed(
  () => app.todayTasks.value.filter((t) => t.completed).length,
);
const items = computed(() =>
  sortTasks(
    app.snapshot.value.tasks.filter(
      (t) =>
        (view.value === "today"
          ? onDay(t, app.state.day)
          : filter.value === "day"
            ? onDay(t, selected.value)
            : filter.value === "unscheduled"
              ? !t.start && !t.included_days.length
              : true) &&
        (!hideDone.value || !t.completed) &&
        (!search.value ||
          `${t.title} ${t.notes} ${t.category}`
            .toLocaleLowerCase()
            .includes(search.value.toLocaleLowerCase())),
    ),
  ),
);
const listTitle = computed(() =>
  view.value === "today"
    ? "今日待办"
    : filter.value === "day"
      ? selected.value
      : filter.value === "unscheduled"
        ? "待安排事项"
        : "全部事项",
);
function edit(task: Task | null = null) {
  editedTask.value = task;
  editing.value = true;
}
function move(delta: number) {
  const date = new Date(month.value + "-15T12:00:00");
  date.setMonth(date.getMonth() + delta);
  month.value = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}
function goToday() {
  selected.value = app.state.day;
  month.value = app.state.day.slice(0, 7);
  filter.value = "day";
}
function choose(day: string) {
  selected.value = day;
  filter.value = "day";
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
  <div v-else class="shell" :inert="editing">
    <aside class="sidebar">
      <div class="brand">
        <span class="brand-mark">✓</span><strong>事项便签</strong>
      </div>
      <nav aria-label="主导航">
        <button
          :class="{ active: view === 'calendar' }"
          @click="view = 'calendar'"
        >
          <CalendarDays :size="19" />事项</button
        ><button :class="{ active: view === 'today' }" @click="view = 'today'">
          <CheckSquare :size="19" />今日待办
          <small>{{ app.todayTasks.value.length - todayCompleted }}</small>
        </button>
      </nav>
      <div class="sidebar-bottom">
        <button @click="app.action('show_sticky')">
          <StickyNote :size="18" />打开桌面便签</button
        ><small>仅显示今日待办<br />可置顶 · 可直接勾选</small>
      </div>
    </aside>
    <main>
      <header class="page-head">
        <div>
          <h1>{{ view === "calendar" ? "事项" : "今日待办" }}</h1>
          <p class="muted">
            {{
              view === "calendar"
                ? "安排日期，按自己的节奏推进。"
                : app.state.day +
                  " · 已完成 " +
                  todayCompleted +
                  " / " +
                  app.todayTasks.value.length
            }}
          </p>
        </div>
        <div class="actions">
          <button @click="app.action('show_sticky')">
            <StickyNote :size="16" />便签</button
          ><button class="primary" :disabled="!app.state.ready" @click="edit()">
            <Plus :size="17" />新增事项
          </button>
        </div>
      </header>
      <div v-if="app.state.error && !editing" class="error-banner" role="alert">
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
          ><button @click="goToday">今天</button><span class="grow" /><button
            :class="{ primary: filter === 'unscheduled' }"
            @click="filter = filter === 'unscheduled' ? 'day' : 'unscheduled'"
          >
            待安排
            {{
              app.snapshot.value.tasks.filter(
                (t) => !t.start && !t.included_days.length,
              ).length
            }}</button
          ><button
            :class="{ primary: filter === 'all' }"
            @click="filter = filter === 'all' ? 'day' : 'all'"
          >
            全部事项
          </button>
        </div>
        <section class="panel calendar" aria-label="事项月历">
          <div class="weekday">
            <span
              v-for="d in ['一', '二', '三', '四', '五', '六', '日']"
              :key="d"
              >周{{ d }}</span
            >
          </div>
          <div class="month-grid">
            <button
              v-for="d in cells"
              :key="d"
              class="day-cell"
              :class="{
                outside: !d.startsWith(month),
                current: d === app.state.day,
                selected: d === selected && filter === 'day',
              }"
              :aria-label="d"
              :aria-pressed="d === selected && filter === 'day'"
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
      <section class="panel list-panel" :class="{ expanded: view === 'today' }">
        <header class="panel-head">
          <h2>
            {{ listTitle }} <small class="muted">{{ items.length }} 项</small>
          </h2>
          <div class="actions">
            <button
              v-if="view === 'today'"
              @click="
                view = 'calendar';
                filter = 'all';
                search = '';
                hideDone = false;
              "
            >
              从已有事项添加
            </button>
            <input
              v-model="search"
              type="search"
              aria-label="搜索事项"
              placeholder="搜索事项 / 备注"
            /><label class="inline-label"
              ><input type="checkbox" v-model="hideDone" />隐藏已完成</label
            >
          </div>
        </header>
        <div class="list-scroll">
          <TaskRows
            :tasks="items"
            :today-actions="view === 'today'"
            @edit="edit"
          />
        </div>
      </section>
      <footer class="app-footer">
        <span>{{ app.state.ready ? "已保存到本机" : "正在读取…" }}</span
        ><span>新增默认今天 · 结束日期留空为单日</span>
      </footer>
    </main>
  </div>
  <TaskEditor
    v-if="!sticky"
    :open="editing"
    :task="editedTask"
    @close="editing = false"
  />
</template>
