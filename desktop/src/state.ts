import { computed, ref, toRaw } from 'vue'
import { defineStore } from 'pinia'
import { call, errorText } from './bridge'
import { today, onDay, projectProgress } from './domain'
import type { Snapshot } from './bindings/Snapshot'
import type { Mutation } from './bindings/Mutation'
import type { Record as WireRecord } from './bindings/Record'
import type { Task } from './bindings/Task'
import type { CaptureStatus } from './bindings/CaptureStatus'
import type { SyncStatus } from './bindings/SyncStatus'
export type Kind = WireRecord['kind']
export type Row<K extends Kind> = {
  uid: string
  data: NonNullable<Extract<WireRecord, { kind: K }>['fields']>
}
export interface Editor {
  kind: Kind
  uid?: string
  project?: string
  stage?: string
}
export const useApp = defineStore('application', () => {
  const snapshot = ref<Snapshot>({ revision: 0, records: {}, local_ids: {} })
  const day = ref(today()),
    noteDraft = ref(''),
    notice = ref(''),
    error = ref(''),
    loading = ref(false)
  const editor = ref<Editor | null>(null),
    deleting = ref<string | null>(null),
    settingsOpen = ref(false),
    financialVisible = ref(false)
  const capture = ref<CaptureStatus>({ running: false, message: '已暂停', exclusions: '' })
  const sync = ref<SyncStatus>({
    busy: false,
    pending: 0,
    message: '尚未检查远端',
    synced_at: null,
    conflicts: [],
    settings: { auto_sync: false, check_on_start: true },
    has_token: false,
  })
  const undo = ref<{ uid: string; expected: Task; previous: Task } | null>(null)
  const rows = <K extends Kind>(kind: K): Row<K>[] =>
    Object.entries(snapshot.value.records)
      .filter(([, r]) => r?.kind === kind && r.fields !== null)
      .map(([uid, r]) => ({ uid, data: r!.fields })) as Row<K>[]
  const tasks = computed(() =>
    rows('tasks').sort(
      (a, b) =>
        Number(a.data.status === '已完成') - Number(b.data.status === '已完成') ||
        ['紧急', '高', '普通', '低'].indexOf(a.data.priority) -
          ['紧急', '高', '普通', '低'].indexOf(b.data.priority) ||
        (snapshot.value.local_ids[a.uid] ?? 0) - (snapshot.value.local_ids[b.uid] ?? 0),
    ),
  )
  const projects = computed(() =>
    rows('projects').sort(
      (a, b) =>
        ['紧急', '高', '普通', '低'].indexOf(a.data.priority) -
        ['紧急', '高', '普通', '低'].indexOf(b.data.priority),
    ),
  )
  const notes = computed(() =>
    rows('notes')
      .sort(
        (a, b) =>
          Date.parse(b.data.created_at) - Date.parse(a.data.created_at) ||
          (snapshot.value.local_ids[b.uid] ?? 0) - (snapshot.value.local_ids[a.uid] ?? 0),
      )
      .slice(0, 200),
  )
  const jobs = computed(() =>
    rows('job_applications').sort((a, b) => b.data.applied_on.localeCompare(a.data.applied_on)),
  )
  const finances = computed(() =>
    rows('finance_entries').sort((a, b) =>
      (b.data.settled_on ?? b.data.occurred_on).localeCompare(
        a.data.settled_on ?? a.data.occurred_on,
      ),
    ),
  )
  const stages = computed(() =>
    rows('milestones').sort(
      (a, b) =>
        Number(a.data.stage_kind === 'ideas') - Number(b.data.stage_kind === 'ideas') ||
        a.data.position - b.data.position ||
        a.uid.localeCompare(b.uid),
    ),
  )
  function progress(uid: string) {
    return projectProgress(
      tasks.value.filter((t) => t.data.project_id === uid).map((t) => t.data),
      new Set(
        stages.value
          .filter((s) => s.data.project_id === uid && s.data.stage_kind === 'standard')
          .map((s) => s.uid),
      ),
    )
  }
  const todayTasks = computed(() => tasks.value.filter((t) => onDay(t.data, day.value)))
  function accept(next: Snapshot) {
    if (next.revision >= snapshot.value.revision) snapshot.value = next
  }
  async function refresh() {
    try {
      accept(await call<Snapshot>('snapshot'))
      error.value = ''
    } catch (e) {
      error.value = errorText(e)
    }
  }
  async function statuses() {
    try {
      const [c, s] = await Promise.all([
        call<CaptureStatus>('capture_status'),
        call<SyncStatus>('sync_status'),
      ])
      capture.value = c
      sync.value = s
    } catch (e) {
      error.value = errorText(e)
    }
  }
  async function change(mutation: Mutation): Promise<boolean> {
    if (loading.value) return false
    loading.value = true
    try {
      accept(
        await call<Snapshot>('mutate', { mutation, expectedRevision: snapshot.value.revision }),
      )
      error.value = ''
      notice.value = '已保存'
      await statuses()
      return true
    } catch (e) {
      error.value = errorText(e)
      await refresh()
      error.value = errorText(e)
      return false
    } finally {
      loading.value = false
    }
  }
  async function complete(row: Row<'tasks'>, completed: boolean) {
    const previous = structuredClone(toRaw(row.data))
    if (await change({ type: 'complete_task', uid: row.uid, completed })) {
      const current = snapshot.value.records[row.uid]
      if (current?.kind === 'tasks' && current.fields)
        undo.value = { uid: row.uid, previous, expected: structuredClone(toRaw(current.fields)) }
      notice.value = completed ? '事项已完成' : '事项已重新打开'
    }
  }
  async function undoCompletion() {
    if (undo.value && (await change({ type: 'undo_task', ...undo.value }))) {
      undo.value = null
      notice.value = '已撤销，完成历史保留'
    }
  }
  async function addNote() {
    if (await change({ type: 'add_note', title: noteDraft.value })) {
      noteDraft.value = ''
      notice.value = '随笔已保存'
    }
  }
  async function openEditor(value: Editor | null) {
    editor.value = value
    await call('set_editing', { editing: value !== null || noteDraft.value.length > 0 }).catch(
      (e) => (error.value = errorText(e)),
    )
  }
  async function toggleCapture() {
    try {
      capture.value = await call<CaptureStatus>('capture_control', {
        running: !capture.value.running,
        exclusions: capture.value.exclusions,
      })
      error.value = ''
    } catch (e) {
      error.value = errorText(e)
    }
  }
  async function runSync(choices: Record<string, string> = {}) {
    try {
      sync.value = { ...sync.value, busy: true }
      sync.value = await call<SyncStatus>('sync_run', { choices })
      await refresh()
      error.value = ''
    } catch (e) {
      error.value = errorText(e)
      await statuses()
    }
  }
  return {
    snapshot,
    day,
    noteDraft,
    notice,
    error,
    loading,
    editor,
    deleting,
    settingsOpen,
    financialVisible,
    capture,
    sync,
    undo,
    rows,
    tasks,
    projects,
    notes,
    jobs,
    finances,
    stages,
    progress,
    todayTasks,
    refresh,
    statuses,
    change,
    complete,
    undoCompletion,
    addNote,
    openEditor,
    toggleCapture,
    runSync,
  }
})
