<script setup lang="ts">
import type { Task } from "../bindings/Task";
import { app } from "../state";
import { onDay } from "../domain";
withDefaults(
  defineProps<{
    tasks: readonly Task[];
    compact?: boolean;
    todayActions?: boolean;
  }>(),
  { compact: false },
);
defineEmits<{ edit: [task: Task] }>();
</script>
<template>
  <p v-if="!tasks.length" class="empty">暂无事项</p>
  <div v-else class="task-list">
    <div
      v-for="t in tasks"
      :key="t.id"
      class="task-row"
      :class="{ done: t.completed, compact }"
      :style="{ '--task-color': t.color }"
    >
      <input
        type="checkbox"
        :aria-label="'完成 ' + t.title"
        :checked="t.completed"
        :disabled="app.state.loading || !app.state.ready"
        @change="
          app.change({ type: 'complete', id: t.id, completed: !t.completed })
        "
      />
      <span v-if="compact" class="task-title" :title="t.title">{{
        t.title
      }}</span>
      <button v-else class="task-title" @click="$emit('edit', t)">
        <span>{{ t.title }}</span
        ><small v-if="t.category !== '其他'">{{ t.category }}</small>
      </button>
      <button
        v-if="!todayActions && !compact && !onDay(t, app.state.day)"
        class="quiet"
        :disabled="app.state.loading"
        :aria-label="'加入今天 ' + t.title"
        @click="
          app.change({
            type: 'today',
            id: t.id,
            day: app.state.day,
            included: true,
          })
        "
      >
        加入今天
      </button>
      <button
        v-if="todayActions && !compact"
        class="quiet"
        :disabled="app.state.loading"
        :aria-label="'移出今天 ' + t.title"
        @click="
          app.change({
            type: 'today',
            id: t.id,
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
