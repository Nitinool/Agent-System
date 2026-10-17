import { describe, it, expect } from 'vitest'
import { amount, onDay, calendarDay, shiftDay, money } from '../src/domain'
import type { Task } from '../src/bindings/Task'
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
  range_start: '2026-10-17',
  range_end: '2026-10-20',
  excluded_days: [],
  days: [],
  completions: [],
}
describe('money and shared date rules', () => {
  it('uses integer cents without floating point rounding', () => {
    expect(amount('128.50')).toBe(12850)
    expect(amount('0.01')).toBe(1)
    expect(amount('1000000000')).toBe(100000000000)
    for (const v of ['0', '-1', '1.001', '1e3', 'NaN', '1000000000.01'])
      expect(() => amount(v)).toThrow()
    expect(money(12850)).toContain('128.50')
  })
  it('includes only the range and respects daily exclusions', () => {
    expect(onDay(task, '2026-10-17')).toBe(true)
    expect(onDay(task, '2026-10-21')).toBe(false)
    expect(onDay({ ...task, excluded_days: ['2026-10-17'] }, '2026-10-17')).toBe(false)
  })
  it('completed ranges leave Today but remain on calendar', () => {
    expect(onDay({ ...task, status: '已完成' }, '2026-10-17')).toBe(false)
    expect(calendarDay({ ...task, status: '已完成' }, '2026-10-17')).toBe(true)
  })
  it('manual membership remains separate from automatic ranges', () => {
    expect(onDay({ ...task, days: ['2026-11-01'] }, '2026-11-01')).toBe(true)
  })
  it('moves through leap day and month boundaries', () => {
    expect(shiftDay('2028-02-28', 1)).toBe('2028-02-29')
    expect(shiftDay('2026-10-31', 1)).toBe('2026-11-01')
  })
})
