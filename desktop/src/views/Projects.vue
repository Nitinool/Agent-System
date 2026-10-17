<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useApp, type Row } from '../state'
import { today, shiftDay } from '../domain'
import TaskList from '../components/TaskList.vue'
const app = useApp(),
  route = useRoute(),
  router = useRouter(),
  selected = ref(''),
  taskId = ref(''),
  start = ref(today()),
  end = ref('')
watch(
  [() => route.query.id, () => app.projects.length],
  () => {
    const id = String(route.query.id ?? '')
    if (app.projects.some((p) => p.uid === id)) selected.value = id
    else if (!app.projects.some((p) => p.uid === selected.value))
      selected.value = app.projects[0]?.uid ?? ''
  },
  { immediate: true },
)
const project = computed(() => app.projects.find((p) => p.uid === selected.value)),
  projectItems = computed(() => app.tasks.filter((t) => t.data.project_id === selected.value)),
  stages = computed(() => app.stages.filter((s) => s.data.project_id === selected.value)),
  progress = computed(() => app.progress(selected.value))
watch(selected, () => {
  taskId.value = ''
})
watch(projectItems, (items) => {
  if (taskId.value && !items.some((t) => t.uid === taskId.value)) taskId.value = ''
})
function chooseTask(row: Row<'tasks'>) {
  taskId.value = row.uid
  start.value = row.data.range_start ?? row.data.planned_on ?? today()
  end.value = row.data.range_end ?? ''
}
function chooseProject(uid: string) {
  selected.value = uid
  void router.replace({ path: '/projects', query: { id: uid } })
}
function period(mode: string) {
  start.value = today()
  if (mode === '今天') end.value = start.value
  else if (mode === '一周') end.value = shiftDay(start.value, 6)
  else {
    const at = new Date(start.value + 'T12:00:00')
    const original = at.getDate()
    at.setDate(1)
    at.setMonth(at.getMonth() + 1)
    const last = new Date(at.getFullYear(), at.getMonth() + 1, 0).getDate()
    at.setDate(Math.min(original, last))
    end.value = shiftDay(
      `${at.getFullYear()}-${String(at.getMonth() + 1).padStart(2, '0')}-${String(at.getDate()).padStart(2, '0')}`,
      -1,
    )
  }
}
</script>
<template>
  <section class="page">
    <header class="page-head">
      <h1>项目</h1>
      <button class="primary" @click="app.openEditor({ kind: 'projects' })">＋ 新建项目</button>
    </header>
    <div class="split">
      <aside class="panel project-list">
        <details
          v-for="[state, label] in [
            ['进行中', 'Active'],
            ['暂停', 'Planning'],
            ['已完成', 'Archive'],
          ]"
          :key="state"
          open
        >
          <summary>
            {{ label }}
            <span class="muted">{{
              app.projects.filter((p) => p.data.status === state).length
            }}</span>
          </summary>
          <button
            v-for="p in app.projects.filter((p) => p.data.status === state)"
            :key="p.uid"
            :class="{ chosen: selected === p.uid }"
            @click="chooseProject(p.uid)"
          >
            <span :class="['priority', p.data.priority]" /><span>{{ p.data.name }}</span
            ><small>#{{ p.uid.slice(0, 8).toUpperCase() }}</small>
          </button>
        </details>
        <div v-if="!app.projects.length" class="empty">暂无项目</div>
      </aside>
      <div v-if="project" class="project-detail">
        <header class="project-header">
          <div>
            <h2><span :class="['priority', project.data.priority]" />{{ project.data.name }}</h2>
            <small class="muted"
              >#{{ project.uid.slice(0, 8).toUpperCase() }} · {{ project.data.category }} ·
              {{ project.data.mode }}</small
            >
          </div>
        </header>
        <div class="toolbar project-actions">
          <button @click="app.openEditor({ kind: 'milestones', project: selected })">
            ＋ 新增阶段
          </button>
          <button @click="app.openEditor({ kind: 'projects', uid: project.uid })">编辑项目</button>
        </div>
        <p v-if="project.data.goal" class="muted project-goal">{{ project.data.goal }}</p>
        <div class="project-progress">
          <div
            class="progress-band"
            :style="
              project.data.mode === '探索型'
                ? { background: `rgba(37,99,235,${1 - Math.exp(-progress.count / 12)})` }
                : {}
            "
          >
            <span
              v-if="project.data.mode === '目标型'"
              :style="{ width: progress.percent + '%' }"
            />
          </div>
          <small>{{
            project.data.mode === '目标型'
              ? progress.total
                ? `${progress.percent}% · ${progress.done}/${progress.total} 完成`
                : '暂无正式事项'
              : `累计 ${progress.count} 次完成 · 当前完成 ${progress.currentDone} 项`
          }}</small>
        </div>
        <div class="stages">
          <details
            v-for="s in stages"
            :key="s.uid"
            :open="s.data.stage_kind === 'standard'"
            class="panel stage"
          >
            <summary>
              <span>{{ s.data.name }}</span
              ><small class="muted"
                >{{
                  projectItems.filter(
                    (t) => t.data.milestone_id === s.uid && t.data.status === '已完成',
                  ).length
                }}
                / {{ projectItems.filter((t) => t.data.milestone_id === s.uid).length }}</small
              ><button
                class="quiet"
                @click.prevent="app.openEditor({ kind: 'tasks', project: selected, stage: s.uid })"
              >
                ＋ 事项</button
              ><button
                v-if="s.data.stage_kind === 'standard'"
                class="quiet"
                @click.prevent="app.openEditor({ kind: 'milestones', uid: s.uid })"
              >
                编辑</button
              ><button
                v-if="s.data.stage_kind === 'standard'"
                class="quiet"
                @click.prevent="app.deleting = s.uid"
              >
                删除
              </button>
            </summary>
            <TaskList
              @select="chooseTask"
              :items="projectItems.filter((t) => t.data.milestone_id === s.uid)"
              :height="
                Math.min(
                  280,
                  Math.max(
                    44,
                    projectItems.filter((t) => t.data.milestone_id === s.uid).length * 44,
                  ),
                )
              "
            />
          </details>
        </div>
        <div class="schedule">
          <select v-model="taskId" aria-label="安排的事项">
            <option value="">选择要安排的事项</option>
            <option v-for="t in projectItems" :value="t.uid">{{ t.data.title }}</option></select
          ><button v-for="p in ['今天', '一周', '一个月']" @click="period(p)">{{ p }}</button
          ><input v-model="start" type="date" aria-label="安排开始" /><span>至</span
          ><input v-model="end" type="date" aria-label="安排结束" /><button
            :disabled="!taskId"
            @click="
              app.change({
                type: 'arrange_task',
                uid: taskId,
                start: start || null,
                end: end || null,
              })
            "
          >
            应用</button
          ><button
            :disabled="!taskId"
            class="quiet"
            @click="app.change({ type: 'arrange_task', uid: taskId, start: null, end: null })"
          >
            清除
          </button>
        </div>
      </div>
      <div v-else class="empty">新建一个项目，开始安排下一步。</div>
    </div>
  </section>
</template>
<style scoped>
.project-list {
  overflow: auto;
}
.project-list summary {
  padding: 12px;
  cursor: pointer;
  font-size: 12px;
  color: #718096;
}
.project-list button {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  width: 100%;
  border: 0;
  text-align: left;
  border-radius: 0;
  padding: 9px 12px;
  background: transparent;
}
.project-list button > span:nth-child(2) {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.project-list button small {
  display: block;
  width: 100%;
  padding: 4px 0 0 13px;
  color: #a0aaba;
  font-size: 10px;
}
.project-list button.chosen {
  background: #eaf1ff;
  color: #1d4ed8;
}
.project-detail {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-width: 0;
}
.project-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}
.project-header h2 {
  font-size: 20px;
  margin: 0 0 4px;
}
.project-goal {
  margin: 0;
}
.project-progress {
  display: flex;
  align-items: center;
  gap: 12px;
}
.project-progress > .progress-band {
  flex: 1;
}
.project-progress small {
  color: #7d8ca0;
  font-size: 12px;
}
.stages {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 250px;
  flex: 1;
}
summary {
  padding: 10px 12px;
  font-size: 13px;
  cursor: pointer;
}
summary small {
  margin-left: 10px;
}
summary button:first-of-type {
  margin-left: 12px;
}
.schedule {
  position: sticky;
  bottom: 0;
  background: #f7f8fa;
  display: flex;
  align-items: center;
  gap: 5px;
  border-top: 1px solid #dfe5ed;
  padding: 8px 0;
  font-size: 11px;
  white-space: nowrap;
}
.schedule input {
  width: 123px;
  font-size: 11px;
  padding: 3px;
}
.schedule select {
  max-width: 160px;
  font-size: 11px;
}
.schedule button {
  font-size: 11px;
  padding: 3px 6px;
}
</style>
