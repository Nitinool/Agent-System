<script setup lang="ts">
import { computed, ref, onMounted, onBeforeUnmount, watch, h } from 'vue'
import { NDataTable, NDrawer, NDrawerContent } from 'naive-ui'
import { useApp } from '../state'
import { call, subscribe, errorText } from '../bridge'
import { duration, shiftDay } from '../domain'
import type { Segment } from '../bindings/Segment'
import TimeChart from '../components/TimeChart.vue'
const app = useApp(),
  day = ref(app.day),
  tab = ref('记录'),
  keyword = ref(''),
  application = ref(''),
  category = ref(''),
  merged = ref(true),
  group = ref('应用'),
  rows = ref<Segment[]>([]),
  detail = ref<Segment | null>(null),
  selected = ref<Array<number | string>>([]),
  classify = ref('未分类')
const display = computed(() => {
  let values = rows.value.map((r) => ({ ...r, refs: [r.id], parts: [r] })).reverse()
  if (merged.value) {
    const out: typeof values = []
    for (const row of values) {
      const previous = out[out.length - 1]
      if (
        previous &&
        row.kind === 'activity' &&
        previous.kind === 'activity' &&
        previous.process === row.process &&
        previous.title === row.title &&
        previous.category === row.category &&
        previous.reason === '查看日志' &&
        row.resume_reason === '查看日志' &&
        Date.parse(row.start) - Date.parse(previous.last_seen) <= 120000 &&
        Date.parse(row.start) >= Date.parse(previous.last_seen)
      ) {
        previous.last_seen = row.last_seen
        previous.end = row.end
        previous.seconds += row.seconds
        previous.status = row.status
        previous.reason = row.reason
        previous.refs.push(...row.refs)
        previous.parts.push(row)
      } else out.push(row)
    }
    values = out
  }
  return values
    .reverse()
    .filter(
      (r) =>
        (!keyword.value ||
          (r.title + r.app + r.process).toLowerCase().includes(keyword.value.toLowerCase())) &&
        (!application.value || r.app === application.value) &&
        (!category.value || r.category === category.value),
    )
    .slice(0, 1000)
})
const chart = computed(() => {
  const map = new Map<string, number>()
  for (const s of rows.value)
    if (s.kind === 'activity') {
      const name = group.value === '应用' ? s.app : s.category
      map.set(name, (map.get(name) ?? 0) + s.seconds)
    }
  return [...map].map(([name, value]) => ({ name, value })).sort((a, b) => b.value - a.value)
})
const total = computed(() =>
  rows.value.filter((s) => s.kind === 'activity').reduce((a, b) => a + b.seconds, 0),
)
const columns = [
  { type: 'selection' as const },
  ...(
    [
      ['start', '开始', 100],
      ['last_seen', '结束 / 最近采样', 140],
      ['seconds', '前台停留', 110],
      ['app', '应用', 160],
      ['title', '窗口 / 页面标题', 420],
      ['category', '分类', 100],
      ['status', '状态', 150],
    ] as const
  ).map(([key, title, width]) => ({
    title,
    key,
    width,
    ellipsis: { tooltip: true },
    render: (r: Segment) =>
      key === 'start' || key === 'last_seen'
        ? new Date(r[key]).toLocaleTimeString('zh-CN', { hour12: false })
        : key === 'seconds'
          ? duration(r.seconds)
          : key === 'status'
            ? r.kind === 'locked'
              ? '锁屏'
              : r.kind === 'gap'
                ? '采集间隔'
                : r.status === 'running'
                  ? '进行中'
                  : r.status === 'interrupted'
                    ? '采集中断'
                    : '已结束'
            : r[key],
  })),
]
let stop: () => void = () => {},
  sequence = 0
async function load() {
  const seq = ++sequence
  try {
    const result = await call<Segment[]>('segments', { day: day.value })
    if (seq === sequence) rows.value = result
  } catch (e) {
    app.error = errorText(e)
  }
}
async function applyClassify() {
  const ids = display.value.filter((r) => selected.value.includes(r.id)).flatMap((r) => r.refs)
  try {
    await call('classify', { ids, category: classify.value })
    await load()
    selected.value = []
  } catch (e) {
    app.error = errorText(e)
  }
}
async function exportCsv(all: boolean) {
  try {
    const path = await call<string | null>('export_csv', {
      day: all ? null : day.value,
      merged: merged.value,
    })
    if (path) app.notice = 'CSV 已导出'
  } catch (e) {
    app.error = errorText(e)
  }
}
async function exclusions() {
  try {
    app.capture = await call('capture_control', {
      running: app.capture.running,
      exclusions: app.capture.exclusions,
    })
  } catch (e) {
    app.error = errorText(e)
  }
}
onMounted(async () => {
  await load()
  stop = await subscribe('capture-changed', load)
})
watch(day, () => {
  selected.value = []
  void load()
})
onBeforeUnmount(() => {
  sequence++
  stop()
})
</script>
<template>
  <section class="page">
    <header class="page-head">
      <h1>
        时间记录 <small>前台停留 {{ duration(total) }}</small>
      </h1>
      <div class="toolbar">
        <button @click="exportCsv(false)">导出当天 CSV</button
        ><button @click="exportCsv(true)">导出全部</button
        ><button :class="{ primary: !app.capture.running }" @click="app.toggleCapture">
          {{ app.capture.running ? '暂停记录' : '开始记录' }}
        </button>
      </div>
    </header>
    <div class="toolbar">
      <button @click="day = shiftDay(day, -1)">‹</button
      ><input v-model="day" type="date" aria-label="记录日期" /><button
        @click="day = shiftDay(day, 1)"
      >
        ›</button
      ><button @click="day = app.day">今天</button><span class="grow" /><span class="muted">{{
        app.capture.message
      }}</span>
    </div>
    <div class="tabs">
      <button v-for="t in ['记录', '统计']" :class="{ selected: tab === t }" @click="tab = t">
        {{ t }}
      </button>
    </div>
    <template v-if="tab === '记录'"
      ><div class="toolbar">
        <input v-model="keyword" placeholder="搜索应用 / 标题" aria-label="搜索时间记录" /><select
          v-model="application"
        >
          <option value="">全部应用</option>
          <option v-for="a in [...new Set(rows.map((r) => r.app))]">{{ a }}</option></select
        ><select v-model="category">
          <option value="">全部分类</option>
          <option v-for="c in ['开发', '学习', '求职', '娱乐', '沟通', '其他', '未分类']">
            {{ c }}
          </option></select
        ><label class="muted"
          ><input type="checkbox" v-model="merged" style="height: auto" />
          合并短暂查看软件的间隔</label
        >
      </div>
      <NDataTable
        :columns="columns"
        :data="display"
        :row-key="(r) => r.id"
        :scroll-x="1300"
        :max-height="480"
        virtual-scroll
        v-model:checked-row-keys="selected"
        :row-props="(r) => ({ onDblclick: () => (detail = r) })"
      />
      <div class="toolbar">
        <span class="muted">显示最近 {{ display.length }} 段</span><span class="grow" /><select
          v-model="classify"
        >
          <option v-for="c in ['开发', '学习', '求职', '娱乐', '沟通', '其他', '未分类']">
            {{ c }}
          </option></select
        ><button :disabled="!selected.length" @click="applyClassify">应用分类</button>
      </div></template
    >
    <section v-else class="panel">
      <div class="panel-head">
        <h2>当天时间分配</h2>
        <select v-model="group">
          <option>应用</option>
          <option>分类</option>
        </select>
      </div>
      <TimeChart :data="chart" />
      <table class="table">
        <thead>
          <tr>
            <th>{{ group }}</th>
            <th>停留时长</th>
            <th>占比</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="s in chart">
            <td>{{ s.name }}</td>
            <td>{{ duration(s.value) }}</td>
            <td>{{ total ? ((s.value / total) * 100).toFixed(1) : 0 }}%</td>
          </tr>
        </tbody>
      </table>
    </section>
    <div class="toolbar">
      <label class="muted">排除进程（逗号分隔）</label
      ><input
        class="grow"
        v-model="app.capture.exclusions"
        placeholder="例如 chrome.exe"
        @change="exclusions"
      />
    </div>
    <NDrawer
      :show="!!detail"
      :width="520"
      @update:show="
        (v) => {
          if (!v) detail = null
        }
      "
      ><NDrawerContent title="记录详情" closable
        ><template v-if="detail"
          ><p>{{ detail.app }}</p>
          <p class="note-text">{{ detail.title }}</p>
          <p class="muted">{{ detail.start }} — {{ detail.last_seen }}</p>
          <p>{{ duration(detail.seconds) }} · {{ detail.category }}</p>
          <p class="muted">{{ detail.reason }}</p>
          <p v-for="s in (detail as Segment & { parts?: Segment[] }).parts" class="muted">
            {{ s.start }} — {{ s.last_seen }} · {{ duration(s.seconds) }}
          </p></template
        ></NDrawerContent
      ></NDrawer
    >
  </section>
</template>
