<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { NModal, NVirtualList, NSelect } from 'naive-ui'
import { Eye, EyeOff } from 'lucide-vue-next'
import { useApp } from '../state'
import { call, subscribe } from '../bridge'
import { money, onDay } from '../domain'
import type { Segment } from '../bindings/Segment'
import TaskList from '../components/TaskList.vue'
import TimeChart from '../components/TimeChart.vue'
const app = useApp(),
  showMoney = computed({
    get: () => app.financialVisible,
    set: (value: boolean) => {
      app.financialVisible = value
    },
  }),
  hideDone = ref(false),
  quick = ref(''),
  note = ref<{ title: string; created_at: string } | null>(null),
  existing = ref<string | null>(null),
  pick = ref(false),
  segments = ref<Segment[]>([])
const month = computed(() => app.day.slice(0, 7)),
  current = computed(() =>
    app.finances.filter(
      (r) => r.data.status !== '待结算' && r.data.settled_on?.startsWith(month.value),
    ),
  )
const income = computed(() =>
    current.value
      .filter((r) => r.data.direction === '收入')
      .reduce((s, r) => s + r.data.amount_cents, 0),
  ),
  expense = computed(() =>
    current.value
      .filter((r) => r.data.direction === '支出')
      .reduce((s, r) => s + r.data.amount_cents, 0),
  )
const chart = computed(() => {
  const map = new Map<string, number>()
  for (const s of segments.value)
    if (s.kind === 'activity') map.set(s.app, (map.get(s.app) ?? 0) + s.seconds)
  return [...map].map(([name, value]) => ({ name, value })).sort((a, b) => b.value - a.value)
})
const visible = computed(() =>
  app.todayTasks.filter((t) => !hideDone.value || t.data.status !== '已完成'),
)
const options = computed(() =>
  app.tasks
    .filter((t) => !onDay(t.data, app.day))
    .map((t) => ({ label: t.data.title, value: t.uid })),
)
function progress(uid: string) {
  return app.progress(uid)
}
async function addQuick() {
  if (
    await app.change({
      type: 'save_task',
      uid: null,
      draft: {
        title: quick.value,
        start: app.day,
        end: null,
        project_id: null,
        milestone_id: null,
        category: '其他',
        notes: '',
      },
    })
  )
    quick.value = ''
}
let stop: () => void = () => {},
  seq = 0
async function load() {
  const n = ++seq
  try {
    const rows = await call<Segment[]>('segments', { day: app.day })
    if (n === seq) segments.value = rows
  } catch {}
}
onMounted(async () => {
  await load()
  stop = await subscribe('capture-changed', load)
})
watch(() => app.day, load)
onBeforeUnmount(() => {
  seq++
  stop()
})
</script>
<template>
  <section class="page home">
    <header class="page-head">
      <h1>
        今日
        <small
          >{{ app.day }} ·
          {{
            new Date(app.day + 'T12:00:00').toLocaleDateString('zh-CN', { weekday: 'long' })
          }}</small
        >
      </h1>
    </header>
    <div class="home-columns">
      <section class="panel today">
        <div class="panel-head">
          <h2>
            今日待办
            <small class="muted"
              >{{ app.todayTasks.filter((t) => t.data.status === '已完成').length }} /
              {{ app.todayTasks.length }}</small
            >
          </h2>
          <label class="muted"><input type="checkbox" v-model="hideDone" /> 隐藏已完成</label>
        </div>
        <form class="quick-entry" @submit.prevent="addQuick">
          <input
            v-model="quick"
            aria-label="快捷事项"
            placeholder="添加今天要做的事…"
            maxlength="120"
          /><button title="添加今日事项" :disabled="app.loading || !quick.trim()">＋</button>
        </form>
        <TaskList :items="visible" today-actions fill /><button
          class="quiet existing"
          @click="pick = true"
        >
          ＋ 从已有事项添加
        </button>
      </section>
      <section class="panel notes">
        <div class="panel-head">
          <h2>随笔</h2>
          <small class="muted">最近 200 条</small>
        </div>
        <form class="note-entry" @submit.prevent="app.addNote">
          <input
            v-model="app.noteDraft"
            aria-label="随笔内容"
            placeholder="记下此刻的想法…"
            maxlength="500"
          /><button :disabled="app.loading || !app.noteDraft.trim()" title="保存随笔">确定</button>
        </form>
        <div v-if="!app.notes.length" class="empty">还没有随笔</div>
        <NVirtualList
          v-else
          :items="app.notes.map((n) => ({ ...n, key: n.uid }))"
          :item-size="36"
          :style="{ height: '0px', flex: '1 1 0', minHeight: '0' }"
          key-field="uid"
          ><template #default="{ item }"
            ><button class="note-row" @click="note = item.data" @dblclick="note = item.data">
              <time>{{
                new Date(item.data.created_at).toLocaleString('zh-CN', {
                  month: '2-digit',
                  day: '2-digit',
                  hour: '2-digit',
                  minute: '2-digit',
                })
              }}</time
              ><span>{{ item.data.title }}</span>
            </button></template
          ></NVirtualList
        >
      </section>
      <div class="home-right">
        <section class="panel">
          <div class="panel-head">
            <h2>{{ month }} 收支</h2>
            <button class="quiet" title="显示或隐藏金额" @click="showMoney = !showMoney">
              <component :is="showMoney ? Eye : EyeOff" :size="16" />
            </button>
          </div>
          <div class="money-grid">
            <div>
              <small class="muted">收入</small>
              <div class="metric">{{ showMoney ? money(income) : '••••' }}</div>
            </div>
            <div>
              <small class="muted">支出</small>
              <div class="metric">{{ showMoney ? money(expense) : '••••' }}</div>
            </div>
          </div>
        </section>
        <section class="panel active-projects">
          <div class="panel-head">
            <h2>进行中的项目</h2>
            <RouterLink to="/projects" class="muted">查看</RouterLink>
          </div>
          <div v-if="!app.projects.some((p) => p.data.status === '进行中')" class="empty">
            暂无进行中的项目
          </div>
          <RouterLink
            v-for="p in app.projects.filter((p) => p.data.status === '进行中')"
            :key="p.uid"
            :to="{ path: '/projects', query: { id: p.uid } }"
            class="home-project"
            ><div><span :class="['priority', p.data.priority]" />{{ p.data.name }}</div>
            <small class="muted">{{
              p.data.mode === '目标型'
                ? progress(p.uid).total
                  ? `${progress(p.uid).done} / ${progress(p.uid).total} 完成`
                  : '暂无正式事项'
                : `累计 ${progress(p.uid).count} 次完成`
            }}</small>
            <div
              class="progress-band"
              :style="
                p.data.mode === '探索型'
                  ? { background: `rgba(37,99,235,${1 - Math.exp(-progress(p.uid).count / 12)})` }
                  : {}
              "
            >
              <span
                v-if="p.data.mode === '目标型'"
                :style="{
                  width: `${progress(p.uid).total ? (progress(p.uid).done / progress(p.uid).total) * 100 : 0}%`,
                }"
              /></div
          ></RouterLink>
        </section>
      </div>
    </div>
    <div class="summary-line">
      求职 <span>已投 {{ app.jobs.length }} 个岗位</span
      ><span>面试中 {{ app.jobs.filter((j) => j.data.status === '面试中').length }}</span
      ><span>Offer {{ app.jobs.filter((j) => j.data.status === '已获 Offer').length }}</span>
    </div>
    <section class="panel time-summary">
      <div class="panel-head">
        <h2>今天的时间分配 <small class="muted">按应用 · 已记录的前台停留</small></h2>
        <RouterLink to="/records" class="muted">查看记录</RouterLink>
      </div>
      <TimeChart :data="chart" />
    </section>
    <NModal
      :show="!!note"
      preset="card"
      title="随笔"
      style="width: 560px"
      @close="note = null"
      closable
      ><template v-if="note"
        ><time class="muted">{{ new Date(note.created_at).toLocaleString('zh-CN') }}</time>
        <p class="note-text">{{ note.title }}</p></template
      ></NModal
    >
    <NModal v-model:show="pick" preset="card" title="添加已有事项" style="width: 440px"
      ><NSelect
        v-model:value="existing"
        :options="options"
        filterable
        placeholder="选择事项"
      /><button
        class="primary"
        style="margin-top: 16px"
        :disabled="!existing"
        @click="
          async () => {
            if (
              existing &&
              (await app.change({ type: 'today', uid: existing, day: app.day, included: true }))
            ) {
              pick = false
              existing = null
            }
          }
        "
      >
        安排今天
      </button></NModal
    >
  </section>
</template>
<style scoped>
.home {
  height: 100%;
  min-height: 0;
}
.home-columns {
  flex: 1;
  min-height: 240px;
  display: grid;
  grid-template-columns: minmax(0, 44fr) minmax(0, 28fr) minmax(0, 28fr);
  gap: 14px;
}
.today,
.notes {
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.today > .empty,
.notes > .empty {
  flex: 1;
  display: grid;
  place-content: center;
}
.time-summary {
  flex-shrink: 0;
}
.time-summary :deep(.chart),
.time-summary :deep(.chart-empty) {
  height: 180px;
}
.note-entry,
.quick-entry {
  display: flex;
  gap: 6px;
  padding: 10px;
}
.note-entry input,
.quick-entry input {
  flex: 1;
  min-width: 0;
}
.note-row {
  width: 100%;
  height: 36px;
  display: flex;
  align-items: center;
  gap: 8px;
  text-align: left;
  border: 0;
  border-bottom: 1px solid #f0f2f6;
  border-radius: 0;
  padding: 6px 12px;
}
.note-row time {
  color: #91a0b2;
  font-size: 10px;
  flex-shrink: 0;
  width: 76px;
}
.note-row span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
  font-size: 13px;
}
.home-right {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: 0;
}
.money-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  padding: 15px 12px;
  gap: 8px;
}
.metric {
  font-size: 18px;
  margin-top: 3px;
}
.active-projects {
  flex: 1;
  min-height: 0;
  overflow: auto;
}
.home-project {
  display: block;
  text-decoration: none;
  color: inherit;
  padding: 9px 12px;
  border-bottom: 1px solid #f0f2f6;
  font-size: 13px;
}
.home-project .progress-band {
  margin-top: 5px;
}
.existing {
  width: 100%;
  font-size: 12px;
  border-top: 1px solid #edf0f5;
  border-radius: 0;
  padding: 8px;
}
.today .panel-head label {
  display: flex;
  align-items: center;
  white-space: nowrap;
  font-size: 10px;
}
.today input[type='checkbox'] {
  height: auto;
}
.home .summary-line {
  padding: 0 4px;
  font-size: 12px;
}
</style>
