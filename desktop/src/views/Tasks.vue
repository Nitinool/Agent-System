<script setup lang="ts">
import { computed, ref } from 'vue'
import { useApp } from '../state'
import { today, shiftDay, calendarDay, colors } from '../domain'
import TaskList from '../components/TaskList.vue'
const app = useApp(),
  selected = ref(today()),
  month = ref(today().slice(0, 7)),
  unscheduled = ref(false)
const cells = computed(() => {
  const first = month.value + '-01'
  const weekday = (new Date(first + 'T12:00:00').getDay() + 6) % 7
  return Array.from({ length: 42 }, (_, i) => shiftDay(first, i - weekday))
})
const list = computed(() =>
  app.tasks.filter((t) =>
    unscheduled.value
      ? !t.data.planned_on && !t.data.range_start
      : calendarDay(t.data, selected.value),
  ),
)
function move(n: number) {
  const at = new Date(month.value + '-15T12:00:00')
  at.setMonth(at.getMonth() + n)
  month.value = `${at.getFullYear()}-${String(at.getMonth() + 1).padStart(2, '0')}`
}
</script>
<template>
  <section class="page">
    <header class="page-head">
      <h1>事项</h1>
      <button class="primary" @click="app.openEditor({ kind: 'tasks' })">＋ 新增事项</button>
    </header>
    <div class="toolbar">
      <button @click="move(-1)">‹</button
      ><input type="month" v-model="month" aria-label="月份" /><button @click="move(1)">›</button
      ><button
        @click="
          () => {
            selected = app.day
            month = app.day.slice(0, 7)
            unscheduled = false
          }
        "
      >
        今天</button
      ><span class="grow" /><button
        :class="{ primary: unscheduled }"
        @click="unscheduled = !unscheduled"
      >
        待安排 {{ app.tasks.filter((t) => !t.data.planned_on && !t.data.range_start).length }}
      </button>
    </div>
    <section class="panel calendar">
      <div class="weekday">
        <span v-for="d in ['一', '二', '三', '四', '五', '六', '日']">周{{ d }}</span>
      </div>
      <div class="month-grid">
        <button
          v-for="d in cells"
          :key="d"
          class="day-cell"
          :class="{
            outside: !d.startsWith(month),
            current: d === app.day,
            selected: d === selected && !unscheduled,
          }"
          @click="
            () => {
              selected = d
              unscheduled = false
            }
          "
        >
          <span class="date-number">{{ Number(d.slice(-2)) }}</span
          ><span
            v-for="t in app.tasks.filter((t) => calendarDay(t.data, d)).slice(0, 3)"
            :key="t.uid"
            class="calendar-task"
            :class="{ done: t.data.status === '已完成' }"
            :style="{
              borderColor: colors[((app.snapshot.local_ids[t.uid] ?? 1) - 1) % colors.length],
            }"
            >{{ t.data.title }}</span
          ><small v-if="app.tasks.filter((t) => calendarDay(t.data, d)).length > 3" class="muted"
            >另 {{ app.tasks.filter((t) => calendarDay(t.data, d)).length - 3 }} 项</small
          >
        </button>
      </div>
    </section>
    <section class="panel">
      <div class="panel-head">
        <h2>{{ unscheduled ? '待安排' : selected }} · {{ list.length }} 项</h2>
      </div>
      <TaskList :items="list" :height="220" />
    </section>
  </section>
</template>
<style scoped>
.weekday,
.month-grid {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
}
.weekday span {
  text-align: center;
  padding: 8px;
  color: #8b98aa;
  font-size: 12px;
}
.day-cell {
  height: 104px;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  border: 0;
  border-top: 1px solid #edf0f5;
  border-right: 1px solid #edf0f5;
  border-radius: 0;
  text-align: left;
  padding: 6px;
  gap: 3px;
  overflow: hidden;
}
.outside {
  background: #fafbfc;
  color: #b5bdc9;
}
.selected {
  background: #eff5ff;
}
.current .date-number {
  color: #2563eb;
  font-weight: 700;
}
.date-number {
  font-size: 12px;
  padding: 0 3px;
}
.calendar-task {
  font-size: 11px;
  border-left: 3px solid;
  padding-left: 5px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  color: #526174;
}
.calendar-task.done {
  opacity: 0.4;
  text-decoration: line-through;
}
.calendar-task:hover {
  background: #edf3fc;
}
.day-cell small {
  font-size: 10px;
}
</style>
