<script setup lang="ts">
import { computed, h, ref } from 'vue'
import { NDataTable, NButton } from 'naive-ui'
import { useApp, type Row } from '../state'
import { jobStatuses } from '../domain'
import { call, errorText } from '../bridge'
const app = useApp(),
  keyword = ref(''),
  status = ref('')
const rows = computed(() =>
  app.jobs.filter(
    (j) =>
      (!status.value || j.data.status === status.value) &&
      (j.data.company + j.data.title + j.data.notes)
        .toLowerCase()
        .includes(keyword.value.toLowerCase()),
  ),
)
const columns = [
  {
    title: '公司',
    key: 'company',
    width: 160,
    render: (r: Row<'job_applications'>) => r.data.company,
  },
  {
    title: '岗位',
    key: 'title',
    width: 180,
    render: (r: Row<'job_applications'>) =>
      h(
        'button',
        {
          class: 'link-button',
          onClick: () => app.openEditor({ kind: 'job_applications', uid: r.uid }),
        },
        r.data.title,
      ),
  },
  ...(
    [
      ['applied_on', '投递日期', 110],
      ['status', '进度', 100],
      ['interview_at', '面试时间', 145],
      ['written_at', '笔试时间', 145],
      ['rejected_at', '拒绝时间', 145],
      ['notes', '备注', 200],
    ] as const
  ).map(([key, title, width]) => ({
    title,
    key,
    width,
    ellipsis: { tooltip: true },
    render: (r: Row<'job_applications'>) => r.data[key] || '—',
  })),
  {
    title: '操作',
    key: 'actions',
    width: 130,
    fixed: 'right' as const,
    render: (r: Row<'job_applications'>) =>
      h('div', { class: 'toolbar' }, [
        h(
          NButton,
          { size: 'tiny', onClick: () => app.openEditor({ kind: 'job_applications', uid: r.uid }) },
          () => '编辑',
        ),
        h(
          NButton,
          {
            size: 'tiny',
            disabled: !r.data.url,
            onClick: async () => {
              try {
                await call('open_job_url', { uid: r.uid })
              } catch (e) {
                app.error = errorText(e)
              }
            },
          },
          () => '链接',
        ),
      ]),
  },
]
</script>
<template>
  <section class="page">
    <header class="page-head">
      <h1>求职</h1>
      <button class="primary" @click="app.openEditor({ kind: 'job_applications' })">
        ＋ 新增已投岗位
      </button>
    </header>
    <div class="summary-line">
      <span>已投 {{ new Set(app.jobs.map((j) => j.data.company.toLowerCase())).size }} 家公司</span
      ><span>{{ app.jobs.length }} 个岗位</span
      ><span>面试中 {{ app.jobs.filter((j) => j.data.status === '面试中').length }}</span
      ><span>Offer {{ app.jobs.filter((j) => j.data.status === '已获 Offer').length }}</span>
    </div>
    <div class="toolbar">
      <input
        v-model="keyword"
        placeholder="搜索公司 / 岗位 / 备注"
        aria-label="搜索投递"
        style="width: 300px"
      /><select v-model="status" aria-label="投递进度筛选">
        <option value="">全部进度</option>
        <option v-for="s in jobStatuses">{{ s }}</option></select
      ><button
        class="quiet"
        @click="
          () => {
            keyword = ''
            status = ''
          }
        "
      >
        清除筛选</button
      ><span class="grow" /><span class="muted">{{ rows.length }} 条</span>
    </div>
    <NDataTable
      :columns="columns"
      :data="rows"
      :row-key="(r) => r.uid"
      :scroll-x="1420"
      :max-height="590"
      virtual-scroll
      :single-line="false"
      :row-props="
        (r) => ({ onDblclick: () => app.openEditor({ kind: 'job_applications', uid: r.uid }) })
      "
    />
  </section>
</template>
