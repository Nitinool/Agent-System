<script setup lang="ts">
import { computed, h } from 'vue'
import { NVirtualList, NButton, NCheckbox } from 'naive-ui'
import { useApp, type Row } from '../state'
import { colors } from '../domain'
const props = withDefaults(
  defineProps<{ items: Row<'tasks'>[]; todayActions?: boolean; height?: number }>(),
  { height: 320 },
)
const app = useApp()
const emit = defineEmits<{ select: [item: Row<'tasks'>] }>()
const items = computed(() => props.items.map((t) => ({ ...t, key: t.uid })))
const projectCode = (id: string | null) => (id ? `#${id.slice(0, 8).toUpperCase()}` : '')
</script>
<template>
  <div v-if="!items.length" class="empty">暂无事项</div>
  <NVirtualList
    v-else
    :style="{ height: height + 'px' }"
    :item-size="44"
    :items="items"
    key-field="uid"
  >
    <template #default="{ item }"
      ><div
        class="task-row"
        @click="emit('select', item)"
        :class="{ done: item.data.status === '已完成' }"
        :style="{
          '--task-color': colors[((app.snapshot.local_ids[item.uid] ?? 1) - 1) % colors.length],
        }"
      >
        <NCheckbox
          :checked="item.data.status === '已完成'"
          :aria-label="'完成 ' + item.data.title"
          :disabled="app.loading"
          @update:checked="(v) => app.complete(item, v)"
        />
        <button class="task-title" @click="app.openEditor({ kind: 'tasks', uid: item.uid })">
          <span>{{ item.data.title }}</span
          ><small v-if="item.data.project_id">{{ projectCode(item.data.project_id) }}</small>
        </button>
        <button
          v-if="todayActions"
          class="quiet task-remove"
          title="移出今天"
          @click="app.change({ type: 'today', uid: item.uid, day: app.day, included: false })"
        >
          移出
        </button>
      </div></template
    >
  </NVirtualList>
</template>
