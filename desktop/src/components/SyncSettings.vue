<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NDrawer, NDrawerContent, NModal } from 'naive-ui'
import { useApp } from '../state'
import { call, errorText } from '../bridge'
import type { SyncStatus } from '../bindings/SyncStatus'
import type { Record as WireRecord } from '../bindings/Record'
const app = useApp(),
  tokenInput = ref<HTMLInputElement>(),
  remember = ref(true),
  auto = ref(false),
  startup = ref(true),
  localError = ref(''),
  choices = ref<Record<string, string>>({})
watch(
  () => app.settingsOpen,
  (show) => {
    if (show) {
      auto.value = app.sync.settings.auto_sync
      startup.value = app.sync.settings.check_on_start
      localError.value = ''
      void app.statuses()
    } else if (tokenInput.value) tokenInput.value.value = ''
  },
)
watch(
  () => app.sync.conflicts,
  () => {
    choices.value = {}
  },
)
async function save(forget = false) {
  const token = tokenInput.value?.value.trim() || null
  if (tokenInput.value) tokenInput.value.value = ''
  try {
    app.sync = await call<SyncStatus>('sync_configure', {
      settings: { auto_sync: auto.value, check_on_start: startup.value },
      token,
      remember: remember.value,
      forget,
    })
    localError.value = ''
  } catch (e) {
    localError.value = errorText(e)
  }
}
const complete = computed(() => app.sync.conflicts.every((c) => choices.value[c.uid]))
const labels: Record<string, string> = {
  name: '名称',
  title: '名称',
  goal: '目标',
  status: '状态',
  priority: '优先级',
  mode: '项目类型',
  created_at: '记录时间',
  company: '公司',
  applied_on: '投递日期',
  url: '链接',
  notes: '备注',
  interview_at: '面试时间',
  written_at: '笔试时间',
  rejected_at: '拒绝时间',
  category: '分类',
  amount_cents: '金额（分）',
  direction: '收支',
  side_source: '副业来源',
  occurred_on: '交易日期',
  settled_on: '到账 / 支付日期',
  project_id: '所属项目',
  milestone_id: '阶段',
  completed_at: '完成时间',
  resume_status: '完成前状态',
  planned_on: '安排日期',
  range_start: '开始日期',
  range_end: '结束日期',
  days: '手动待办日期',
  excluded_days: '跳过日期',
  completions: '完成历史',
  kind: '类型',
  acceptance: '验收记录',
  outcome: '成果',
  position: '阶段顺序',
  stage_kind: '阶段类型',
}
function preview(r: WireRecord) {
  if (r.fields === null) return '已删除'
  return Object.entries(r.fields)
    .map(
      ([key, value]) =>
        `${labels[key] ?? key}：${value === null || value === '' ? '未填写' : key === 'stage_kind' ? (value === 'ideas' ? '未来想法' : '普通阶段') : typeof value === 'object' ? JSON.stringify(value, null, 2) : value}`,
    )
    .join('\n')
}
async function cancel() {
  try {
    await call('sync_cancel')
    await app.statuses()
  } catch (e) {
    app.error = errorText(e)
  }
}
</script>
<template>
  <NDrawer :show="app.settingsOpen" :width="480" @update:show="(v) => (app.settingsOpen = v)"
    ><NDrawerContent title="数据同步与设置" closable
      ><div class="form">
        <div>
          <strong>GitHub 双机同步</strong>
          <p class="muted">
            Nitinool/Agent-System-data<br />新版：sync/v2/records.json<br />随笔、事项、项目、求职与财务参与同步，行为日志仅在本机。
          </p>
        </div>
        <div class="sync-state">
          <b>{{ app.sync.message }}</b
          ><small
            >本机待同步 {{ app.sync.pending }} 条 ·
            {{ app.sync.settings.auto_sync ? '自动' : '手动' }}模式</small
          ><small
            >上次完成：{{
              app.sync.synced_at ? new Date(app.sync.synced_at).toLocaleString('zh-CN') : '尚未同步'
            }}</small
          ><small>待同步 0 条只表示本机没有待上传修改。</small>
        </div>
        <button class="primary" :disabled="app.sync.busy" @click="app.runSync()">
          {{ app.sync.busy ? '同步中…' : '立即同步' }}
        </button>
        <hr />
        <label
          >GitHub Token<input
            ref="tokenInput"
            type="password"
            autocomplete="off"
            :placeholder="
              app.sync.has_token ? '已配置，留空继续使用' : '填写 Fine-grained Token'
            " /></label
        ><small
          >仅选择上述私有仓库，Contents 权限为 Read and
          write。新版需单独配置一次，不复用旧版凭据。</small
        ><label class="check"
          ><input type="checkbox" v-model="remember" />在本机记住（Windows 加密）</label
        ><label class="check"
          ><input type="checkbox" v-model="startup" />启动时检查（手动模式只提示，不导入）</label
        ><label class="check"
          ><input type="checkbox" v-model="auto" />自动同步（停止修改后；每 5 分钟检查远端）</label
        >
        <div class="toolbar">
          <button @click="save(false)">保存设置</button
          ><button class="quiet danger" @click="save(true)">清除本机 Token</button>
        </div>
        <button class="link-button" @click="call('open_token_page')">创建 GitHub Token ↗</button>
        <p v-if="localError" class="error" role="alert">{{ localError }}</p>
        <hr />
        <p class="muted">
          数据目录：%LOCALAPPDATA%/Agent-System-V2/<br />关闭窗口会退出并停止采集；每次启动默认暂停。<br />旧版数据和同步文件保持独立。
        </p>
      </div></NDrawerContent
    ></NDrawer
  >
  <NModal
    :show="app.sync.conflicts.length > 0 && app.settingsOpen"
    preset="card"
    title="处理同步冲突"
    style="width: 880px; max-height: 85vh; overflow: auto"
    :closable="false"
    ><section v-for="c in app.sync.conflicts" :key="c.uid" class="conflict">
      <h3>
        {{
          c.local.fields && 'title' in c.local.fields
            ? c.local.fields.title
            : c.local.fields && 'name' in c.local.fields
              ? c.local.fields.name
              : '删除记录'
        }}
      </h3>
      <div class="versions">
        <label
          ><input type="radio" :name="c.uid" value="local" v-model="choices[c.uid]" /> 保留本机
          <pre>{{ preview(c.local) }}</pre></label
        ><label
          ><input type="radio" :name="c.uid" value="remote" v-model="choices[c.uid]" /> 保留远端
          <pre>{{ preview(c.remote) }}</pre>
        </label>
      </div>
    </section>
    <div class="form-actions">
      <button @click="cancel">取消本次同步</button
      ><button class="primary" :disabled="!complete || app.sync.busy" @click="app.runSync(choices)">
        应用选择并同步
      </button>
    </div></NModal
  >
</template>
<style scoped>
.check {
  flex-direction: row;
  align-items: center;
}
.check input {
  height: auto;
}
.sync-state {
  display: flex;
  flex-direction: column;
  gap: 7px;
  font-size: 13px;
}
.sync-state small {
  color: #7b8ca2;
}
.versions {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.versions label {
  border: 1px solid #dce3ed;
  padding: 12px;
  border-radius: 5px;
  font-size: 13px;
}
.versions input {
  height: auto;
}
.versions pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  max-height: 300px;
  overflow: auto;
  font:
    12px/1.6 'Microsoft YaHei UI',
    sans-serif;
  color: #65748a;
}
.conflict h3 {
  font-size: 14px;
}
hr {
  border: 0;
  border-top: 1px solid #edf0f5;
  width: 100%;
}
</style>
