<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { NDrawer, NDrawerContent, NModal } from 'naive-ui'
import { useApp } from '../state'
import { priorities, categories, jobStatuses, amount, today } from '../domain'
import { errorText } from '../bridge'
import type { Mutation } from '../bindings/Mutation'
const app = useApp(),
  router = useRouter(),
  localError = ref(''),
  discard = ref(false),
  initial = ref('')
const categoryTouched = ref(false)
let initializing = false
const f = reactive({
  name: '',
  goal: '',
  title: '',
  start: '',
  end: '',
  project_id: '',
  milestone_id: '',
  category: '其他',
  notes: '',
  status: '',
  priority: '普通',
  mode: '目标型',
  company: '',
  applied_on: '',
  url: '',
  interview_at: '',
  written_at: '',
  rejected_at: '',
  direction: '支出',
  amount: '',
  occurred_on: '',
  side_source: '',
  settled_on: '',
  acceptance: '',
  position: 1,
  completed_at: null as string | null,
})
const title = computed(
  () =>
    `${app.editor?.uid ? '编辑' : '新增'}${{ tasks: '事项', projects: '项目', milestones: '阶段', job_applications: '已投岗位', finance_entries: '账目', notes: '随笔' }[app.editor?.kind ?? 'tasks']}`,
)
watch(
  () => app.editor,
  (editor) => {
    if (!editor) return
    initializing = true
    categoryTouched.value = false
    localError.value = ''
    const r = editor.uid ? app.snapshot.records[editor.uid] : null
    Object.assign(f, {
      name: '',
      goal: '',
      title: '',
      start: '',
      end: '',
      project_id: editor.project ?? '',
      milestone_id: editor.stage ?? '',
      category:
        editor.kind === 'tasks'
          ? (app.projects.find((p) => p.uid === editor.project)?.data.category ?? '其他')
          : '其他',
      notes: '',
      status:
        editor.kind === 'projects'
          ? '进行中'
          : editor.kind === 'job_applications'
            ? '已投递'
            : '已支付',
      priority: '普通',
      mode: '目标型',
      company: '',
      applied_on: today(),
      url: '',
      interview_at: '',
      written_at: '',
      rejected_at: '',
      direction: '支出',
      amount: '',
      occurred_on: today(),
      side_source: '',
      settled_on: today(),
      acceptance: '',
      position:
        app.stages.filter(
          (s) => s.data.project_id === editor.project && s.data.stage_kind === 'standard',
        ).length + 1,
      completed_at: null,
    })
    if (r?.fields) {
      Object.assign(f, r.fields)
      if (r.kind === 'tasks') {
        f.milestone_id = r.fields.milestone_id ?? ''
        f.start = r.fields.range_start ?? r.fields.planned_on ?? ''
        f.end = r.fields.range_end === f.start ? '' : (r.fields.range_end ?? '')
      }
      if (r.kind === 'finance_entries') f.amount = (r.fields.amount_cents / 100).toFixed(2)
    }
    initial.value = JSON.stringify(f)
    initializing = false
  },
  { immediate: true },
)
watch(
  () => f.project_id,
  () => {
    if (initializing || app.editor?.kind !== 'tasks') return
    f.milestone_id = ''
    if (!app.editor.uid && !categoryTouched.value)
      f.category = app.projects.find((p) => p.uid === f.project_id)?.data.category ?? '其他'
  },
  { flush: 'sync' },
)
const availableStages = computed(() => app.stages.filter((s) => s.data.project_id === f.project_id))
function close() {
  if (JSON.stringify(f) !== initial.value) discard.value = true
  else void app.openEditor(null)
}
async function save() {
  const e = app.editor
  if (!e) return
  let mutation: Mutation
  localError.value = ''
  try {
    switch (e.kind) {
      case 'tasks':
        if (f.project_id && !f.milestone_id) throw { message: '请选择所属阶段。' }
        mutation = {
          type: 'save_task',
          uid: e.uid ?? null,
          draft: {
            title: f.title,
            start: f.start || null,
            end: f.end || null,
            project_id: f.project_id || null,
            category: f.category,
            notes: f.notes,
            milestone_id: f.project_id ? f.milestone_id || null : null,
          },
        }
        break
      case 'projects':
        mutation = {
          type: 'save_project',
          uid: e.uid ?? null,
          draft: {
            name: f.name,
            goal: f.goal,
            status: f.status,
            priority: f.priority,
            mode: f.mode,
            category: f.category,
          },
        }
        break
      case 'milestones':
        mutation = {
          type: 'save_milestone',
          uid: e.uid ?? null,
          draft: {
            stage_kind: 'standard',
            project_id: f.project_id,
            name: f.name,
            acceptance: f.acceptance,
            position: f.position,
            completed_at: f.completed_at,
          },
        }
        break
      case 'job_applications':
        mutation = {
          type: 'save_job',
          uid: e.uid ?? null,
          draft: {
            company: f.company,
            title: f.title,
            applied_on: f.applied_on,
            status: f.status,
            url: f.url,
            notes: f.notes,
            interview_at: f.interview_at,
            written_at: f.written_at,
            rejected_at: f.rejected_at,
          },
        }
        break
      case 'finance_entries':
        mutation = {
          type: 'save_finance',
          uid: e.uid ?? null,
          draft: {
            direction: f.direction,
            amount_cents: amount(f.amount),
            occurred_on: f.occurred_on,
            title: f.title,
            category: f.category,
            side_source: f.side_source,
            status: f.direction === '支出' ? '已支付' : f.status,
            settled_on:
              f.direction === '收入' && f.status === '待结算' ? null : f.settled_on || null,
            notes: f.notes,
          },
        }
        break
      default:
        return
    }
    if (await app.change(mutation)) {
      const created =
        e.kind === 'projects' && !e.uid
          ? app.projects.find((p) => p.data.name === f.name.trim())
          : null
      await app.openEditor(null)
      if (created) await router.push({ path: '/projects', query: { id: created.uid } })
    } else localError.value = app.error
  } catch (error) {
    localError.value = errorText(error)
  }
}
const jobPreview = computed(() =>
  f.rejected_at
    ? '已拒绝'
    : ['已获 Offer', '已撤回'].includes(f.status)
      ? f.status
      : f.interview_at
        ? '面试中'
        : f.written_at
          ? '笔试中'
          : f.status,
)
</script>
<template>
  <NDrawer
    :show="!!app.editor"
    :width="440"
    :mask-closable="false"
    @update:show="
      (v) => {
        if (!v) close()
      }
    "
    ><NDrawerContent :title="title" closable @close="close">
      <form id="entity-editor" class="form" @submit.prevent="save">
        <template v-if="app.editor?.kind === 'projects'"
          ><label>项目名称<input v-model="f.name" maxlength="120" autofocus required /></label
          ><label>项目目标<textarea v-model="f.goal" /></label>
          <label
            >分类<select v-model="f.category" aria-label="分类">
              <option v-for="c in categories">{{ c }}</option>
            </select></label
          >
          <div class="two">
            <label
              >优先级<select v-model="f.priority" aria-label="优先级">
                <option v-for="p in priorities">{{ p }}</option>
              </select></label
            ><label
              >类型<select v-model="f.mode" aria-label="类型">
                <option>目标型</option>
                <option>探索型</option>
              </select></label
            >
          </div>
          <label
            >分组<select v-model="f.status" aria-label="分组">
              <option value="进行中">Active</option>
              <option value="暂停">Planning</option>
              <option value="已完成">Archive</option>
            </select></label
          ></template
        >
        <template v-else-if="app.editor?.kind === 'milestones'"
          ><label>阶段标题<input v-model="f.name" maxlength="120" required /></label
        ></template>
        <template v-else-if="app.editor?.kind === 'tasks'"
          ><label>事项名称<input v-model="f.title" maxlength="120" required /></label>
          <div class="two">
            <label>开始日期<input v-model="f.start" type="date" /></label
            ><label
              >结束日期（可选）<input v-model="f.end" type="date" :min="f.start || undefined"
            /></label>
          </div>
          <label
            >所属项目<select v-model="f.project_id" aria-label="所属项目">
              <option value="">无项目</option>
              <option v-for="p in app.projects" :value="p.uid">{{ p.data.name }}</option>
            </select></label
          ><label v-if="f.project_id"
            >所属阶段<select v-model="f.milestone_id" aria-label="所属阶段" required>
              <option value="" disabled>请选择阶段</option>
              <option v-for="s in availableStages" :key="s.uid" :value="s.uid">
                {{ s.data.name }}
              </option>
            </select></label
          ><label
            >分类<select v-model="f.category" aria-label="分类" @change="categoryTouched = true">
              <option v-for="c in categories">{{ c }}</option>
            </select></label
          ><label>备注<textarea v-model="f.notes" rows="8" /></label
        ></template>
        <template v-else-if="app.editor?.kind === 'job_applications'"
          ><label
            >公司<input
              v-model="f.company"
              list="company-history"
              maxlength="120"
              required /></label
          ><datalist id="company-history">
            <option
              v-for="name in [...new Set(app.jobs.map((j) => j.data.company))]"
              :value="name"
            /></datalist
          ><label>岗位<input v-model="f.title" list="job-history" maxlength="120" required /></label
          ><datalist id="job-history">
            <option v-for="name in [...new Set(app.jobs.map((j) => j.data.title))]" :value="name" />
          </datalist>
          <div class="two">
            <label>投递日期<input v-model="f.applied_on" type="date" required /></label
            ><label
              >进度<select v-model="f.status" aria-label="进度">
                <option v-for="s in jobStatuses">{{ s }}</option>
              </select></label
            >
          </div>
          <label
            v-for="[key, label] in [
              ['interview_at', '面试时间'],
              ['written_at', '笔试时间'],
              ['rejected_at', '拒绝时间'],
            ] as const"
            >{{ label
            }}<input v-model="f[key]" placeholder="YYYY-MM-DD 或 YYYY-MM-DD HH:MM" /></label
          ><small>保存进度：{{ jobPreview }}</small
          ><label>岗位链接<input v-model="f.url" type="url" placeholder="https://" /></label
          ><label>备注<textarea v-model="f.notes" /></label
        ></template>
        <template v-else-if="app.editor?.kind === 'finance_entries'"
          ><div class="two">
            <label
              >方向<select
                aria-label="方向"
                v-model="f.direction"
                @change="f.status = f.direction === '支出' ? '已支付' : '已到账'"
              >
                <option>收入</option>
                <option>支出</option>
              </select></label
            ><label
              >金额（元）<input v-model="f.amount" inputmode="decimal" placeholder="0.00" required
            /></label>
          </div>
          <label>名称<input v-model="f.title" maxlength="120" required /></label>
          <div class="two">
            <label>交易日期<input v-model="f.occurred_on" type="date" required /></label
            ><label
              >分类<input v-model="f.category" list="finance-categories" maxlength="100" required
            /></label>
          </div>
          <datalist id="finance-categories">
            <option
              v-for="c in [
                ...new Set([
                  '其他',
                  '餐饮',
                  '交通',
                  '购物',
                  '住房',
                  '工资',
                  '副业收入',
                  ...app.finances.map((r) => r.data.category),
                ]),
              ]"
              :value="c"
            /></datalist
          ><label
            >副业来源<input v-model="f.side_source" list="source-history" maxlength="100" /></label
          ><datalist id="source-history">
            <option
              v-for="s in [...new Set(app.finances.map((r) => r.data.side_source).filter(Boolean))]"
              :value="s"
            /></datalist
          ><label v-if="f.direction === '收入'"
            >到账状态<select v-model="f.status" aria-label="到账状态">
              <option>已到账</option>
              <option>待结算</option>
            </select></label
          ><label v-if="f.direction === '支出' || f.status !== '待结算'"
            >到账 / 支付日期<input
              v-model="f.settled_on"
              type="date"
              :min="f.occurred_on"
              required /></label
          ><label>备注<textarea v-model="f.notes" /></label
        ></template>
        <p v-if="localError" class="error" role="alert">{{ localError }}</p>
      </form>
      <template #footer
        ><div class="form-actions">
          <button v-if="app.editor?.uid" class="danger" @click="app.deleting = app.editor.uid">
            删除</button
          ><button @click="close">取消</button
          ><button class="primary" form="entity-editor" type="submit" :disabled="app.loading">
            {{ app.loading ? '保存中…' : '保存' }}
          </button>
        </div></template
      >
    </NDrawerContent></NDrawer
  >
  <NModal
    v-model:show="discard"
    preset="dialog"
    title="放弃修改？"
    content="尚未保存的输入会丢失。"
    positive-text="放弃"
    negative-text="继续编辑"
    @positive-click="
      () => {
        discard = false
        app.openEditor(null)
      }
    "
  />
</template>
