<script setup lang="ts">
import { computed, ref } from "vue";
import { Pin, PinOff, ExternalLink } from "lucide-vue-next";
import { app } from "./state";
import TaskRows from "./components/TaskRows.vue";
const pinned = ref(true);
const completed = computed(
  () => app.todayTasks.value.filter((t) => t.completed).length,
);
async function pin() {
  const next = !pinned.value;
  if (await app.action("set_pinned", { pinned: next })) pinned.value = next;
}
</script>
<template>
  <main class="sticky">
    <header class="sticky-header">
      <div>
        <h1>
          今日待办
          <small>{{ completed }} / {{ app.todayTasks.value.length }}</small>
        </h1>
        <p>{{ app.state.day }}</p>
      </div>
      <div class="actions">
        <button
          class="quiet"
          :aria-label="pinned ? '取消置顶' : '置顶便签'"
          :aria-pressed="pinned"
          :title="pinned ? '取消置顶' : '置顶便签'"
          @click="pin"
        >
          <Pin v-if="pinned" :size="17" /><PinOff v-else :size="17" /></button
        ><button
          class="quiet"
          aria-label="打开主窗口"
          title="打开主窗口"
          @click="app.action('show_main')"
        >
          <ExternalLink :size="17" />
        </button>
      </div>
    </header>
    <p v-if="app.state.error" class="error sticky-error" role="alert">
      {{ app.state.error }} <button @click="app.refresh()">重试</button>
    </p>
    <div class="sticky-list">
      <TaskRows :tasks="app.todayTasks.value" compact />
    </div>
    <footer class="sticky-footer">
      <span>{{
        app.state.ready
          ? app.todayTasks.value.length
            ? "今天，逐项完成。"
            : "今天还没有安排。"
          : "正在读取…"
      }}</span
      ><button class="quiet" @click="app.action('quit_app')">退出应用</button>
    </footer>
  </main>
</template>
