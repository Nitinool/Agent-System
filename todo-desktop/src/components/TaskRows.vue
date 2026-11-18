<script setup lang="ts">
import { computed, ref } from "vue";
import type { Task } from "../bindings/Task";
import { app } from "../state";
import {
  doneOn,
  onDay,
  orderedTree,
  priorityColor,
  priorityTitle,
  shortDay,
} from "../domain";

const props = withDefaults(
  defineProps<{
    tasks: readonly Task[];
    compact?: boolean;
    todayActions?: boolean;
    showProject?: boolean;
    reorderable?: boolean;
  }>(),
  { compact: false, showProject: false, reorderable: false },
);
defineEmits<{ edit: [task: Task] }>();

const rows = computed(() => orderedTree(props.tasks));
const topLevel = computed(() => rows.value.filter((row) => row.depth === 0));
const labels = computed(
  () => new Map(app.snapshot.value.labels.map((label) => [label.id, label])),
);
const projects = computed(
  () => new Map(app.snapshot.value.projects.map((project) => [project.id, project])),
);
const dragged = ref<string | null>(null);

function when(task: Task) {
  if (!task.start) return "待安排";
  if (!task.end || task.end === task.start) return shortDay(task.start);
  return `${shortDay(task.start)}–${shortDay(task.end)}`;
}
function projectName(task: Task) {
  return task.project_id ? projects.value.get(task.project_id)?.name : null;
}
function start(event: DragEvent, id: string) {
  dragged.value = id;
  event.dataTransfer?.setData("text/plain", id);
  if (event.dataTransfer) event.dataTransfer.effectAllowed = "move";
}
function drop(target: string) {
  const moving = dragged.value;
  dragged.value = null;
  if (!moving || moving === target) return;
  const ids = topLevel.value.map((row) => row.task.id);
  const from = ids.indexOf(moving);
  const to = ids.indexOf(target);
  if (from < 0 || to < 0) return;
  ids.splice(to, 0, ids.splice(from, 1)[0]);
  void app.change({ type: "task_reorder", ids });
}
</script>

<template>
  <p v-if="!rows.length" class="empty">暂无事项</p>
  <div v-else class="task-list">
    <div
      v-for="row in rows"
      :key="row.task.id"
      class="task-row"
      :class="{
        done: doneOn(row.task, app.state.day),
        compact,
        subtask: row.depth > 0,
        dragging: dragged === row.task.id,
      }"
      :style="{
        '--task-color': row.task.color,
        paddingLeft: 12 + row.depth * 18 + 'px',
      }"
      :draggable="reorderable && row.depth === 0"
      @dragstart="reorderable && start($event, row.task.id)"
      @dragover.prevent
      @drop.prevent="reorderable && drop(row.task.id)"
      @dragend="dragged = null"
    >
      <span
        class="priority-bar"
        :style="{ background: priorityColor(row.task.priority) }"
        :title="priorityTitle(row.task.priority)"
      />
      <input
        type="checkbox"
        :aria-label="'完成 ' + row.task.title"
        :checked="doneOn(row.task, app.state.day)"
        :disabled="app.state.loading || !app.state.ready"
        @change="
          app.change({
            type: 'task_complete',
            id: row.task.id,
            completed: !doneOn(row.task, app.state.day),
          })
        "
      />
      <template v-if="compact">
        <span class="task-title" :title="row.task.title">{{ row.task.title }}</span>
      </template>
      <button v-else class="task-title" @click="$emit('edit', row.task)">
        <span>{{ row.task.title }}</span>
        <span class="task-meta">
          <span
            v-for="id in row.task.label_ids"
            :key="id"
            class="chip"
            :style="{ color: labels.get(id)?.color, borderColor: labels.get(id)?.color }"
            >{{ labels.get(id)?.name }}</span
          >
          <small v-if="showProject && projectName(row.task)" class="muted">{{
            projectName(row.task)
          }}</small>
          <small class="muted">{{ when(row.task) }}</small>
        </span>
      </button>
      <button
        v-if="!row.task.recurrence && !todayActions && !compact && !onDay(row.task, app.state.day)"
        class="quiet"
        :disabled="app.state.loading"
        :aria-label="'加入今天 ' + row.task.title"
        @click="
          app.change({
            type: 'task_today',
            id: row.task.id,
            day: app.state.day,
            included: true,
          })
        "
      >
        加入今天
      </button>
      <button
        v-if="!row.task.recurrence && todayActions && !compact"
        class="quiet"
        :disabled="app.state.loading"
        :aria-label="'移出今天 ' + row.task.title"
        @click="
          app.change({
            type: 'task_today',
            id: row.task.id,
            day: app.state.day,
            included: false,
          })
        "
      >
        移出
      </button>
    </div>
  </div>
</template>
