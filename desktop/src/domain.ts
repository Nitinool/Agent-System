import type { Task } from './bindings/Task'
export function projectProgress(tasks: Task[], formalStageIds: ReadonlySet<string>) {
  const formal = tasks.filter((t) => t.milestone_id && formalStageIds.has(t.milestone_id))
  const done = formal.filter((t) => t.status === '已完成').length
  return {
    total: formal.length,
    done,
    percent: formal.length ? Math.round((done / formal.length) * 100) : 0,
    count: tasks.reduce((n, t) => n + t.completions.length, 0),
    currentDone: tasks.filter((t) => t.status === '已完成').length,
  }
}
export const priorities = ['紧急', '高', '普通', '低']
export const categories = ['其他', '开发', '学习', '求职', '生活', '娱乐', '沟通']
export const jobStatuses = ['已投递', '笔试中', '面试中', '已获 Offer', '已拒绝', '已撤回']
export function today(): string {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}
export function shiftDay(day: string, delta: number): string {
  const at = new Date(`${day}T12:00:00`)
  at.setDate(at.getDate() + delta)
  return `${at.getFullYear()}-${String(at.getMonth() + 1).padStart(2, '0')}-${String(at.getDate()).padStart(2, '0')}`
}
export function onDay(task: Task, day: string): boolean {
  return (
    task.days.includes(day) ||
    (!!task.range_start &&
      !!task.range_end &&
      task.range_start <= day &&
      day <= task.range_end &&
      !task.excluded_days.includes(day))
  )
}
export function calendarDay(task: Task, day: string): boolean {
  return (
    task.planned_on === day ||
    (!!task.range_start && !!task.range_end && task.range_start <= day && day <= task.range_end)
  )
}
export function amount(text: string): number {
  if (!/^\d+(\.\d{1,2})?$/.test(text.trim())) throw { message: '金额请输入正数，最多两位小数。' }
  const [whole, part = ''] = text.trim().split('.')
  const cents = Number(whole) * 100 + Number(part.padEnd(2, '0'))
  if (!Number.isSafeInteger(cents) || cents <= 0 || cents > 100_000_000_000)
    throw { message: '金额必须大于零，且不超过十亿元。' }
  return cents
}
export function money(cents: number): string {
  return new Intl.NumberFormat('zh-CN', { style: 'currency', currency: 'CNY' }).format(cents / 100)
}
export function duration(seconds: number): string {
  const n = Math.max(0, Math.floor(seconds))
  return n >= 3600
    ? `${Math.floor(n / 3600)}时${Math.floor((n % 3600) / 60)}分`
    : n >= 60
      ? `${Math.floor(n / 60)}分${n % 60}秒`
      : `${n}秒`
}
export const colors = [
  '#3b82f6',
  '#8b5cf6',
  '#0891b2',
  '#ca8a04',
  '#db2777',
  '#16a34a',
  '#ea580c',
  '#6366f1',
  '#0d9488',
  '#b45309',
  '#9333ea',
  '#475569',
]
