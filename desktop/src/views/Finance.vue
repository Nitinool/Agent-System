<script setup lang="ts">
import { computed, ref, h } from 'vue'
import { NDataTable, NButton, NDrawer, NDrawerContent } from 'naive-ui'
import { useApp, type Row } from '../state'
import { money, amount } from '../domain'
import { errorText } from '../bridge'
const app = useApp(),
  tab = ref('流水'),
  month = ref(app.day.slice(0, 7)),
  source = ref(''),
  settling = ref<Row<'finance_entries'> | null>(null),
  settleAmount = ref(''),
  settleDay = ref(app.day),
  settleError = ref('')
const pending = computed(() => app.finances.filter((r) => r.data.status === '待结算'))
const paid = computed(() =>
  app.finances.filter(
    (r) =>
      r.data.status !== '待结算' && (!month.value || r.data.settled_on?.startsWith(month.value)),
  ),
)
const income = computed(() =>
    paid.value
      .filter((r) => r.data.direction === '收入')
      .reduce((s, r) => s + r.data.amount_cents, 0),
  ),
  expense = computed(() =>
    paid.value
      .filter((r) => r.data.direction === '支出')
      .reduce((s, r) => s + r.data.amount_cents, 0),
  )
const sources = computed(() => [
  ...new Set(app.finances.map((r) => r.data.side_source).filter(Boolean)),
])
const rows = computed(() =>
  (tab.value === '待结算'
    ? pending.value
    : app.finances.filter(
        (r) => !month.value || (r.data.settled_on ?? r.data.occurred_on).startsWith(month.value),
      )
  ).filter((r) => !source.value || r.data.side_source === source.value),
)
function openSettle(r: Row<'finance_entries'>) {
  settling.value = r
  settleAmount.value = (r.data.amount_cents / 100).toFixed(2)
  settleDay.value = app.day
  settleError.value = ''
}
async function settle() {
  try {
    if (
      settling.value &&
      (await app.change({
        type: 'settle',
        uid: settling.value.uid,
        day: settleDay.value,
        amount_cents: amount(settleAmount.value),
      }))
    )
      settling.value = null
    else settleError.value = app.error
  } catch (e) {
    settleError.value = errorText(e)
  }
}
const columns = [
  {
    title: '名称',
    key: 'title',
    width: 180,
    render: (r: Row<'finance_entries'>) =>
      h(
        'button',
        {
          class: 'link-button',
          onClick: () => app.openEditor({ kind: 'finance_entries', uid: r.uid }),
        },
        r.data.title,
      ),
  },
  ...(
    [
      ['direction', '收支', 70],
      ['occurred_on', '交易日期', 110],
      ['settled_on', '到账 / 支付', 110],
      ['category', '分类', 100],
      ['side_source', '副业来源', 140],
      ['status', '状态', 90],
      ['notes', '备注', 180],
    ] as const
  ).map(([key, title, width]) => ({
    title,
    key,
    width,
    ellipsis: { tooltip: true },
    render: (r: Row<'finance_entries'>) => r.data[key] || '—',
  })),
  {
    title: '金额',
    key: 'amount',
    width: 120,
    render: (r: Row<'finance_entries'>) => money(r.data.amount_cents),
  },
  {
    title: '操作',
    key: 'action',
    width: 150,
    fixed: 'right' as const,
    render: (r: Row<'finance_entries'>) =>
      h('div', { class: 'toolbar' }, [
        h(
          NButton,
          { size: 'tiny', onClick: () => app.openEditor({ kind: 'finance_entries', uid: r.uid }) },
          () => '编辑',
        ),
        ...(r.data.status === '待结算'
          ? [
              h(
                NButton,
                { size: 'tiny', type: 'primary', onClick: () => openSettle(r) },
                () => '确认到账',
              ),
            ]
          : []),
      ]),
  },
]
function totals(s: string) {
  const r = paid.value.filter((r) => r.data.side_source.toLowerCase() === s.toLowerCase())
  const inc = r
      .filter((r) => r.data.direction === '收入')
      .reduce((s, r) => s + r.data.amount_cents, 0),
    exp = r.filter((r) => r.data.direction === '支出').reduce((s, r) => s + r.data.amount_cents, 0)
  return {
    income: inc,
    expense: exp,
    net: inc - exp,
    pending: pending.value
      .filter((r) => r.data.side_source.toLowerCase() === s.toLowerCase())
      .reduce((s, r) => s + r.data.amount_cents, 0),
  }
}
</script>
<template>
  <section class="page">
    <header class="page-head">
      <h1>财务</h1>
      <button class="primary" @click="app.openEditor({ kind: 'finance_entries' })">
        ＋ 记一笔
      </button>
    </header>
    <div class="summary-line">
      <span
        >到账收入 <b>{{ money(income) }}</b></span
      ><span
        >已支付出 <b>{{ money(expense) }}</b></span
      ><span
        >收支结余 <b>{{ money(income - expense) }}</b></span
      ><span
        >全部待结算 <b>{{ money(pending.reduce((s, r) => s + r.data.amount_cents, 0)) }}</b></span
      >
    </div>
    <div class="tabs">
      <button
        v-for="t in ['流水', '副业统计', '待结算']"
        :class="{ selected: tab === t }"
        @click="tab = t"
      >
        {{ t }} {{ t === '待结算' ? pending.length : '' }}
      </button>
    </div>
    <div class="toolbar">
      <label v-if="tab !== '待结算'"
        >月份 <input v-model="month" type="month" aria-label="账目月份" /></label
      ><span v-else class="muted">包含全部月份的待结算收入</span
      ><select v-model="source" aria-label="来源筛选">
        <option value="">全部来源</option>
        <option v-for="s in sources">{{ s }}</option>
      </select>
    </div>
    <div v-if="tab === '副业统计'" class="panel table-scroll">
      <table class="table">
        <thead>
          <tr>
            <th>来源</th>
            <th>到账收入</th>
            <th>已付成本</th>
            <th>净额</th>
            <th>全部待结算</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="s in sources">
            <td>{{ s }}</td>
            <td>{{ money(totals(s).income) }}</td>
            <td>{{ money(totals(s).expense) }}</td>
            <td>{{ money(totals(s).net) }}</td>
            <td>{{ money(totals(s).pending) }}</td>
          </tr>
        </tbody>
      </table>
      <div v-if="!sources.length" class="empty">暂无副业来源</div>
    </div>
    <NDataTable
      v-else
      :columns="columns"
      :data="rows"
      :row-key="(r) => r.uid"
      :scroll-x="1400"
      :max-height="570"
      virtual-scroll
    />
    <NDrawer
      :show="!!settling"
      :width="420"
      @update:show="
        (v) => {
          if (!v) settling = null
        }
      "
      ><NDrawerContent title="确认到账" closable
        ><form id="settle-form" class="form" @submit.prevent="settle">
          <p>{{ settling?.data.title }}</p>
          <label
            >实际到账金额（元）<input v-model="settleAmount" inputmode="decimal" required /></label
          ><label
            >实际到账日期<input
              type="date"
              v-model="settleDay"
              :min="settling?.data.occurred_on"
              required
          /></label>
          <p v-if="settleError" class="error">{{ settleError }}</p>
        </form>
        <template #footer
          ><button class="primary" form="settle-form" type="submit">确认到账</button></template
        ></NDrawerContent
      ></NDrawer
    >
  </section>
</template>
