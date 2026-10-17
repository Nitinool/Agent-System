import { test, expect } from '@playwright/test'
// This bridge exists only in the test browser; the desktop never seeds production data.
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    let revision = 0
    let records: Record<string, unknown> = {}
    let local = 0
    let fail = false
    const status = {
      busy: false,
      pending: 0,
      message: '尚未检查远端',
      synced_at: null,
      conflicts: [],
      settings: { auto_sync: false, check_on_start: true },
      has_token: false,
    }
    const ids: Record<string, number> = {}
    ;(window as any).__TEST_FAIL__ = () => {
      fail = true
    }
    ;(window as any).__TEST_BRIDGE__ = async (command: string, args: any) => {
      if (command === 'snapshot') return { revision, records, local_ids: ids }
      if (command === 'capture_status') return { running: false, message: '已暂停', exclusions: '' }
      if (command === 'sync_status') return status
      if (command === 'segments') return []
      if (['app_ready', 'set_editing'].includes(command)) return null
      if (command === 'mutate') {
        if (fail) {
          fail = false
          throw { message: '模拟磁盘写入失败' }
        }
        const m = args.mutation,
          id = m.uid ?? (++local).toString(16).padStart(32, '0')
        ids[id] = local
        if (m.type === 'add_note') {
          if (!m.title.trim()) throw { message: '请填写随笔' }
          records[id] = {
            kind: 'notes',
            fields: { title: m.title, created_at: new Date().toISOString() },
          }
        }
        if (m.type === 'save_project') records[id] = { kind: 'projects', fields: m.draft }
        if (m.type === 'save_task') {
          if (m.draft.end && !m.draft.start) throw { message: '请先填写开始日期' }
          records[id] = {
            kind: 'tasks',
            fields: {
              title: m.draft.title,
              planned_on: m.draft.start,
              range_start: m.draft.start,
              range_end: m.draft.end ?? m.draft.start,
              category: m.draft.category,
              notes: m.draft.notes,
              status: '待开始',
              priority: '普通',
              kind: '任务',
              project_id: m.draft.project_id,
              milestone_id: m.draft.milestone_id,
              resume_status: '待开始',
              acceptance: '',
              outcome: '',
              completed_at: null,
              days: [],
              excluded_days: [],
              completions: [],
            },
          }
        }
        revision++
        return { revision, records, local_ids: ids }
      }
      throw { message: '未模拟的调用 ' + command }
    }
  })
})
test('six pages, compact navigation and empty startup', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: '今日', exact: false }).first()).toBeVisible()
  await expect(page.getByText('••••')).toHaveCount(2)
  for (const [nav, title] of [
    ['事项', '事项'],
    ['项目', '项目'],
    ['时间记录', '时间记录'],
    ['求职', '求职'],
    ['财务', '财务'],
  ]) {
    await page.getByRole('navigation').getByRole('link', { name: nav, exact: true }).click()
    await expect(page.getByRole('heading', { name: title, exact: false }).first()).toBeVisible()
  }
  await page.getByTitle('收起或展开导航').click()
  await expect(page.locator('.shell')).toHaveClass(/collapsed/)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})
test('note save, failure retains draft and route changes preserve unsubmitted input', async ({
  page,
}) => {
  await page.goto('/')
  const input = page.getByRole('textbox', { name: '随笔内容' })
  await input.fill('新的随笔')
  await input.press('Enter')
  await expect(input).toHaveValue('')
  await expect(page.getByText('新的随笔', { exact: true })).toBeVisible()
  await input.fill('保留草稿')
  await page.evaluate(() => (window as any).__TEST_FAIL__())
  await input.press('Enter')
  await expect(input).toHaveValue('保留草稿')
  await page.getByRole('navigation').getByRole('link', { name: '项目', exact: true }).click()
  await page.getByRole('navigation').getByRole('link', { name: '今日', exact: true }).click()
  await expect(input).toHaveValue('保留草稿')
})
test('project drawer save and failed task editor remains intact', async ({ page }) => {
  await page.goto('/#/projects')
  await page.getByRole('button', { name: '新建项目', exact: false }).click()
  await page.getByLabel('项目名称', { exact: true }).fill('重构项目')
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.getByRole('heading', { name: '重构项目' })).toBeVisible()
  await page.getByRole('button', { name: '新增事项', exact: false }).click()
  await page.getByLabel('事项名称').fill('测试事项')
  await page.evaluate(() => (window as any).__TEST_FAIL__())
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.getByLabel('事项名称')).toHaveValue('测试事项')
  await expect(page.locator('#entity-editor').getByRole('alert')).toContainText('模拟磁盘写入失败')
})
for (const scale of [1.25, 1.5])
  test(`layout at 1100x700 and ${scale * 100}% scale`, async ({ browser }) => {
    const context = await browser.newContext({
      viewport: { width: 1100, height: 700 },
      deviceScaleFactor: scale,
    })
    const page = await context.newPage()
    await page.goto('/')
    await expect(page.getByRole('heading', { name: '今日', exact: false }).first()).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await context.close()
  })
