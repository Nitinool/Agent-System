import { beforeEach, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { reactive } from 'vue'
import { call } from '../src/bridge'
import { useApp } from '../src/state'
import type { Task } from '../src/bindings/Task'
vi.mock('../src/bridge', () => ({
  call: vi.fn(),
  errorText: (e: { message: string }) => e.message,
}))
beforeEach(() => {
  setActivePinia(createPinia())
  vi.resetAllMocks()
})
it('completion snapshots Vue proxies safely and submits a typed mutation', async () => {
  const app = useApp(),
    uid = 'a'.repeat(32)
  const task: Task = {
    title: '事项',
    planned_on: null,
    category: '其他',
    notes: '',
    status: '待开始',
    priority: '普通',
    kind: '任务',
    project_id: null,
    resume_status: '待开始',
    milestone_id: null,
    acceptance: '',
    outcome: '',
    completed_at: null,
    range_start: null,
    range_end: null,
    excluded_days: [],
    days: [],
    completions: [],
  }
  app.snapshot = {
    revision: 1,
    records: { [uid]: { kind: 'tasks', fields: task } },
    local_ids: { [uid]: 1 },
  }
  vi.mocked(call).mockImplementation(async (command) => {
    if (command === 'mutate')
      return {
        revision: 2,
        records: { [uid]: { kind: 'tasks', fields: { ...task, status: '已完成' } } },
        local_ids: { [uid]: 1 },
      } as never
    if (command === 'capture_status')
      return { running: false, message: '已暂停', exclusions: '' } as never
    return {
      busy: false,
      pending: 1,
      message: '本机有修改',
      synced_at: null,
      conflicts: [],
      settings: { auto_sync: false, check_on_start: true },
      has_token: false,
    } as never
  })
  await app.complete(reactive({ uid, data: task }), true)
  expect(call).toHaveBeenCalledWith('mutate', {
    mutation: { type: 'complete_task', uid, completed: true },
    expectedRevision: 1,
  })
  expect(app.undo?.previous.status).toBe('待开始')
  expect(app.undo?.expected.status).toBe('已完成')
})
it('stale snapshots never replace a newer accepted revision', async () => {
  const app = useApp()
  app.snapshot = { revision: 5, records: {}, local_ids: {} }
  vi.mocked(call).mockResolvedValue({ revision: 3, records: {}, local_ids: {} })
  await app.refresh()
  expect(app.snapshot.revision).toBe(5)
})
