<script setup lang="ts">
import type { Label } from "../bindings/Label";

defineProps<{ labels: readonly Label[]; selected: readonly string[] }>();
const emit = defineEmits<{ toggle: [id: string]; clear: [] }>();
</script>

<template>
  <div v-if="labels.length" class="filter-bar" role="group" aria-label="标签筛选">
    <span class="filter-title">只看标签</span>
    <button
      v-for="label in labels"
      :key="label.id"
      class="filter-chip"
      :class="{ on: selected.includes(label.id) }"
      :style="{ '--chip': label.color }"
      :aria-pressed="selected.includes(label.id)"
      @click="emit('toggle', label.id)"
    >
      {{ label.name }}
    </button>
    <button v-if="selected.length" class="quiet" @click="emit('clear')">
      显示全部
    </button>
    <small v-else class="muted">不选＝全部</small>
  </div>
</template>
