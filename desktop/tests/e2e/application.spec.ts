import { test, expect } from '@playwright/test'

test('financial editor submits integer cents and retains failed drafts', async ({ page }) => {
  await page.goto('/#/finance')
  await page.getByRole('button', { name: '记一笔', exact: false }).click()
  await page.getByLabel('方向', { exact: true }).selectOption('收入')
  await page.getByLabel('金额（元）', { exact: true }).fill('128.50')
  await page.getByLabel('名称', { exact: true }).fill('待结算测试')
  await page.getByLabel('副业来源', { exact: true }).fill('测试来源')
  await page.getByLabel('到账状态', { exact: true }).selectOption('待结算')
  await page.evaluate(() => (window as any).__TEST_FAIL__())
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.getByLabel('金额（元）', { exact: true })).toHaveValue('128.50')
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.locator('#entity-editor')).toHaveCount(0)
  const snapshot = await page.evaluate(() => (window as any).__TEST_BRIDGE__('snapshot', {}))
  expect((Object.values(snapshot.records)[0] as any).fields.amount_cents).toBe(12850)
  expect((Object.values(snapshot.records)[0] as any).fields.settled_on).toBeNull()
})

test('1500 tasks and 150 today rows stay virtualized with stable navigation', async ({ page }) => {
  const day = new Date().toLocaleDateString('sv-SE'),
    projectId = 'f'.repeat(32)
  const fixture: Record<string, unknown> = {
    [projectId]: {
      kind: 'projects',
      fields: {
        name: '重构项目',
        goal: '让每日行动清晰可见',
        status: '进行中',
        priority: '高',
        mode: '目标型',
      },
    },
  }
  for (let i = 1; i <= 1500; i++)
    fixture[i.toString(16).padStart(32, '0')] = {
      kind: 'tasks',
      fields: {
        title: `事项 ${i}`,
        planned_on: i <= 150 ? day : null,
        range_start: i <= 150 ? day : null,
        range_end: i <= 150 ? day : null,
        category: '开发',
        notes: '',
        status: '待开始',
        priority: '普通',
        kind: '任务',
        project_id: projectId,
        milestone_id: null,
        resume_status: '待开始',
        acceptance: '',
        outcome: '',
        completed_at: null,
        days: [],
        excluded_days: [],
        completions: [],
      },
    }
  for (let i = 1501; i <= 1505; i++)
    fixture[i.toString(16).padStart(32, '0')] = {
      kind: 'notes',
      fields: {
        title: [
          '完成项目布局讨论',
          '今天先处理最重要的事项',
          '记录真实进展',
          '保持页面紧凑',
          '下一步验证双机同步',
        ][i - 1501],
        created_at: new Date().toISOString(),
      },
    }
  await page.addInitScript((records) => {
    ;(window as any).__TEST_INITIAL_RECORDS__ = records
  }, fixture)
  const start = Date.now()
  await page.goto('/')
  await expect(page.getByText('事项 1', { exact: true })).toBeVisible()
  const startupMs = Date.now() - start,
    rendered = await page.locator('.task-row').count()
  expect(rendered).toBeLessThan(50)
  await page.screenshot({ path: 'test-results/workbench-1440.png' })
  const navStart = Date.now()
  for (let i = 0; i < 5; i++)
    await page.getByRole('navigation').getByRole('link', { name: '今日', exact: true }).click()
  console.log(
    JSON.stringify({
      fixtureTasks: 1500,
      todayTasks: 150,
      renderedRows: rendered,
      browserStartupMs: startupMs,
      repeatedHomeMs: Date.now() - navStart,
    }),
  )
  await page.getByTitle('显示或隐藏金额').click()
  await page.getByRole('navigation').getByRole('link', { name: '项目', exact: true }).click()
  await page.getByRole('navigation').getByRole('link', { name: '今日', exact: true }).click()
  await expect(page.getByText('••••')).toHaveCount(0)
  await page.setViewportSize({ width: 1100, height: 700 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: 'test-results/workbench-1100.png' })
})
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
      if (command === 'snapshot') {
        if ((window as any).__TEST_INITIAL_RECORDS__) {
          records = (window as any).__TEST_INITIAL_RECORDS__
          delete (window as any).__TEST_INITIAL_RECORDS__
          for (const id of Object.keys(records)) ids[id] = ++local
          revision++
        }
        return { revision, records, local_ids: ids }
      }
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
        if (m.type === 'save_finance') records[id] = { kind: 'finance_entries', fields: m.draft }
        if (m.type === 'save_job') records[id] = { kind: 'job_applications', fields: m.draft }
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

test('project search keeps true stage progress and scheduling selects task identity', async ({
  page,
}) => {
  const project = 'a'.repeat(32),
    other = 'b'.repeat(32),
    stage = 'c'.repeat(32)
  const first = 'd'.repeat(32),
    second = 'e'.repeat(32)
  const projectFields = { goal: '', status: '进行中', priority: '普通', mode: '目标型' }
  const taskFields = {
    planned_on: null,
    range_start: null,
    range_end: null,
    category: '其他',
    notes: '',
    status: '待开始',
    priority: '普通',
    kind: '任务',
    project_id: project,
    milestone_id: stage,
    resume_status: '待开始',
    acceptance: '',
    outcome: '',
    completed_at: null,
    days: [],
    excluded_days: [],
    completions: [],
  }
  await page.addInitScript(
    (records) => {
      ;(window as any).__TEST_INITIAL_RECORDS__ = records
    },
    {
      [project]: { kind: 'projects', fields: { ...projectFields, name: '当前项目' } },
      [other]: { kind: 'projects', fields: { ...projectFields, name: '另一个项目' } },
      [stage]: {
        kind: 'milestones',
        fields: {
          project_id: project,
          name: '第一阶段',
          position: 0,
          goal: '',
          acceptance: '',
          verified_at: null,
        },
      },
      [first]: { kind: 'tasks', fields: { ...taskFields, title: '事项' } },
      [second]: { kind: 'tasks', fields: { ...taskFields, title: '事项延长' } },
    },
  )
  await page.goto('/#/projects?id=' + project)
  await expect(page.locator('.stage summary')).toContainText('0 / 2')
  await page.getByLabel('搜索项目事项').fill('延长')
  await expect(page.locator('.task-row')).toHaveCount(1)
  await expect(page.locator('.stage summary')).toContainText('0 / 2')
  await page.locator('.task-row').dispatchEvent('click')
  await expect(page.getByLabel('安排的事项')).toHaveValue(second)
  await page.getByRole('button', { name: /另一个项目/ }).click()
  await expect(page.getByLabel('安排的事项')).toHaveValue('')
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
