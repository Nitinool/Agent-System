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
        category: '开发',
      },
    },
  }
  fixture['e'.repeat(32)] = {
    kind: 'milestones',
    fields: {
      project_id: projectId,
      name: '开发阶段',
      stage_kind: 'standard',
      position: 1,
      acceptance: '',
      completed_at: null,
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
        milestone_id: 'e'.repeat(32),
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
    let records: Record<string, any> = {}
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
    function seedIdeas(project: string) {
      if (
        Object.values(records).some(
          (r) =>
            r.kind === 'milestones' &&
            r.fields?.project_id === project &&
            r.fields?.stage_kind === 'ideas',
        )
      )
        return
      const uid = '9' + (++local).toString(16).padStart(31, '0')
      ids[uid] = local
      records[uid] = {
        kind: 'milestones',
        fields: {
          project_id: project,
          name: '未来想法',
          stage_kind: 'ideas',
          position: 4294967295,
          acceptance: '',
          completed_at: null,
        },
      }
    }
    ;(window as any).__TEST_FAIL__ = () => {
      fail = true
    }
    ;(window as any).__TEST_BRIDGE__ = async (command: string, args: any) => {
      if (command === 'snapshot') {
        if ((window as any).__TEST_INITIAL_RECORDS__) {
          records = (window as any).__TEST_INITIAL_RECORDS__
          delete (window as any).__TEST_INITIAL_RECORDS__
          for (const id of Object.keys(records)) ids[id] = ++local
          for (const id of Object.keys(records)) if (records[id].kind === 'projects') seedIdeas(id)
          revision++
        }
        return { revision, records, local_ids: ids }
      }
      if (command === 'capture_status') return { running: false, message: '已暂停', exclusions: '' }
      if (command === 'sync_status') return status
      if (command === 'segments') return (window as any).__TEST_SEGMENTS__ ?? []
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
        if (m.type === 'save_project') {
          records[id] = { kind: 'projects', fields: m.draft }
          seedIdeas(id)
        }
        if (m.type === 'save_milestone') records[id] = { kind: 'milestones', fields: m.draft }
        if (m.type === 'complete_task') {
          const t = records[id].fields
          t.status = m.completed ? '已完成' : '待开始'
          if (m.completed)
            t.completions.push({
              title: t.title,
              project_id: t.project_id,
              completed_at: new Date().toISOString(),
              reopened_at: null,
            })
          else if (t.completions.length) t.completions.at(-1).reopened_at = new Date().toISOString()
        }
        if (m.type === 'today') {
          const t = records[id].fields
          t.days = t.days.filter((d: string) => d !== m.day)
          t.excluded_days = t.excluded_days.filter((d: string) => d !== m.day)
          if (m.included) t.days.push(m.day)
          else t.excluded_days.push(m.day)
        }
        if (m.type === 'delete') {
          if (
            Object.values(records).some((r) => r.kind === 'tasks' && r.fields?.milestone_id === id)
          )
            throw { message: '阶段中还有事项，请先移动或删除其中事项。' }
          records[id] = { kind: records[id].kind, fields: null }
        }
        if (m.type === 'save_finance') records[id] = { kind: 'finance_entries', fields: m.draft }
        if (m.type === 'save_job') records[id] = { kind: 'job_applications', fields: m.draft }
        if (m.type === 'save_task') {
          if (m.draft.end && !m.draft.start) throw { message: '请先填写开始日期' }
          if (m.draft.project_id && !m.draft.milestone_id)
            throw { message: '项目事项必须选择所属阶段。' }
          const previous = records[id]?.fields
          records[id] = {
            kind: 'tasks',
            fields: {
              title: m.draft.title,
              planned_on: m.draft.start,
              range_start: m.draft.start,
              range_end: m.draft.end ?? m.draft.start,
              category: m.draft.category,
              notes: m.draft.notes,
              status: previous?.status ?? '待开始',
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
              completions: previous?.completions ?? [],
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
  await page.locator('.stage').getByRole('button', { name: '事项', exact: false }).click()
  await page.getByLabel('事项名称').fill('测试事项')
  await page.evaluate(() => (window as any).__TEST_FAIL__())
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.getByLabel('事项名称')).toHaveValue('测试事项')
  await expect(page.locator('#entity-editor').getByRole('alert')).toContainText('模拟磁盘写入失败')
})

test('compact stages retain counts and scheduling selects task identity', async ({ page }) => {
  const project = 'a'.repeat(32),
    other = 'b'.repeat(32),
    stage = 'c'.repeat(32)
  const first = 'd'.repeat(32),
    second = 'e'.repeat(32)
  const projectFields = {
    goal: '',
    status: '进行中',
    priority: '普通',
    mode: '目标型',
    category: '开发',
  }
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
          stage_kind: 'standard',
          acceptance: '',
          completed_at: null,
        },
      },
      [first]: { kind: 'tasks', fields: { ...taskFields, title: '事项' } },
      [second]: { kind: 'tasks', fields: { ...taskFields, title: '事项延长' } },
    },
  )
  await page.goto('/#/projects?id=' + project)
  const formal = page
    .locator('.stage')
    .filter({ has: page.locator('summary > span', { hasText: '第一阶段' }) })
  await expect(formal.locator('summary')).toContainText('0 / 2')
  await expect(page.getByLabel('搜索项目事项')).toHaveCount(0)
  await expect(page.getByText('完成历史', { exact: true })).toHaveCount(0)
  await expect(page.getByText('已完成事项', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '新增事项', exact: false })).toHaveCount(0)
  await page.locator('.task-row').filter({ hasText: '事项延长' }).dispatchEvent('click')
  await expect(page.getByLabel('安排的事项')).toHaveValue(second)
  await page.getByRole('button', { name: /另一个项目/ }).click()
  await expect(page.getByLabel('安排的事项')).toHaveValue('')
})
test('category defaults respect overrides and every project editor requires a stage', async ({
  page,
}) => {
  await page.goto('/#/projects')
  const created: Record<string, string> = {}
  for (const [name, category] of [
    ['项目甲', '开发'],
    ['项目乙', '学习'],
  ]) {
    await page.getByRole('button', { name: '新建项目', exact: false }).click()
    await page.getByLabel('项目名称', { exact: true }).fill(name!)
    await page.getByLabel('分类', { exact: true }).selectOption(category!)
    await page.getByRole('button', { name: '保存', exact: true }).click()
    await expect(page.getByRole('heading', { name: name!, exact: true })).toBeVisible()
    created[name!] = await page.evaluate(async (name) => {
      const s = await (window as any).__TEST_BRIDGE__('snapshot', {})
      return Object.entries(s.records).find(
        ([, r]: any) => r.kind === 'projects' && r.fields.name === name,
      )![0]
    }, name)
  }
  await page.getByRole('navigation').getByRole('link', { name: '事项', exact: true }).click()
  await page.getByRole('button', { name: '新增事项', exact: false }).click()
  await page.getByLabel('事项名称').fill('跨项目草稿')
  await page.getByLabel('所属项目', { exact: true }).selectOption(created['项目甲']!)
  await expect(page.getByLabel('分类', { exact: true })).toHaveValue('开发')
  await expect(page.getByLabel('所属阶段', { exact: true })).toHaveValue('')
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.locator('#entity-editor')).toBeVisible()
  await page.getByLabel('所属项目', { exact: true }).selectOption(created['项目乙']!)
  await expect(page.getByLabel('分类', { exact: true })).toHaveValue('学习')
  const ideas = await page
    .getByLabel('所属阶段', { exact: true })
    .locator('option')
    .last()
    .getAttribute('value')
  await page.getByLabel('所属阶段', { exact: true }).selectOption(ideas!)
  await page.getByLabel('分类', { exact: true }).selectOption('生活')
  await page.getByLabel('所属项目', { exact: true }).selectOption(created['项目甲']!)
  await expect(page.getByLabel('分类', { exact: true })).toHaveValue('生活')
  await expect(page.getByLabel('所属阶段', { exact: true })).toHaveValue('')
  const ideaA = await page
    .getByLabel('所属阶段', { exact: true })
    .locator('option')
    .last()
    .getAttribute('value')
  await page.getByLabel('所属阶段', { exact: true }).selectOption(ideaA!)
  await page.evaluate(() => (window as any).__TEST_FAIL__())
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.getByLabel('所属阶段', { exact: true })).toHaveValue(ideaA!)
  await expect(page.getByLabel('分类', { exact: true })).toHaveValue('生活')
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await page.getByRole('navigation').getByRole('link', { name: '项目', exact: true }).click()
  await page.getByRole('button', { name: /项目甲/ }).click()
  await page.getByRole('button', { name: '编辑项目', exact: true }).click()
  await page.getByLabel('分类', { exact: true }).selectOption('沟通')
  await page.getByRole('button', { name: '保存', exact: true }).click()
  const ideaStage = page
    .locator('.stage')
    .filter({ has: page.locator('summary > span', { hasText: '未来想法' }) })
  await expect(ideaStage).not.toHaveAttribute('open', '')
  await expect(ideaStage.getByRole('button', { name: '编辑', exact: true })).toHaveCount(0)
  await expect(ideaStage.getByRole('button', { name: '删除', exact: true })).toHaveCount(0)
  await ideaStage.locator('summary').click()
  await ideaStage.getByRole('button', { name: '跨项目草稿', exact: false }).click()
  await expect(page.getByLabel('分类', { exact: true })).toHaveValue('生活')
  await expect(page.getByLabel('所属阶段', { exact: true })).toHaveValue(ideaA!)
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await page.getByRole('navigation').getByRole('link', { name: '今日', exact: true }).click()
  await page.getByLabel('快捷事项').fill('主页项目事项')
  await page.getByLabel('快捷事项').press('Enter')
  await page.getByRole('button', { name: '主页项目事项', exact: false }).click()
  await page.getByLabel('所属项目', { exact: true }).selectOption(created['项目甲']!)
  await expect(page.getByLabel('分类', { exact: true })).toHaveValue('其他')
  await expect(page.getByLabel('所属阶段', { exact: true })).toHaveValue('')
  await page.getByLabel('所属阶段', { exact: true }).selectOption(ideaA!)
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.locator('#entity-editor')).toHaveCount(0)
})

test('completed items stay in their stage and ideas do not inflate target progress', async ({
  page,
}) => {
  await page.goto('/#/projects')
  await page.getByRole('button', { name: '新建项目', exact: false }).click()
  await page.getByLabel('项目名称', { exact: true }).fill('阶段反馈')
  await page.getByLabel('分类', { exact: true }).selectOption('开发')
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await page.getByRole('button', { name: '新增阶段', exact: false }).click()
  await page.getByLabel('阶段标题').fill('开发阶段')
  await page.getByRole('button', { name: '保存', exact: true }).click()
  const formal = page
    .locator('.stage')
    .filter({ has: page.locator('summary > span', { hasText: '开发阶段' }) })
  for (const title of ['功能甲', '功能乙']) {
    await formal.getByRole('button', { name: '事项', exact: false }).click()
    await page.getByLabel('事项名称').fill(title)
    await expect(page.getByLabel('分类', { exact: true })).toHaveValue('开发')
    await page.getByRole('button', { name: '保存', exact: true }).click()
  }
  await formal.getByRole('checkbox', { name: '完成 功能甲' }).click()
  await expect(formal.getByRole('checkbox', { name: '完成 功能甲' })).toBeChecked()
  await expect(formal.locator('.task-row').last()).toHaveClass(/done/)
  await expect(page.locator('.project-progress')).toContainText('50%')
  await formal.getByRole('button', { name: '功能甲', exact: false }).click()
  const idea = await page
    .getByLabel('所属阶段', { exact: true })
    .locator('option')
    .last()
    .getAttribute('value')
  await page.getByLabel('所属阶段', { exact: true }).selectOption(idea!)
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.locator('.project-progress')).toContainText('0%')
  const ideas = page
    .locator('.stage')
    .filter({ has: page.locator('summary > span', { hasText: '未来想法' }) })
  await ideas.locator('summary').click()
  await expect(ideas.getByRole('checkbox', { name: '完成 功能甲' })).toBeChecked()
  await page.screenshot({ path: 'test-results/projects-1440.png' })
  await page.setViewportSize({ width: 1100, height: 700 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: 'test-results/projects-1100.png' })
  await page.getByRole('navigation').getByRole('link', { name: '今日', exact: true }).click()
  await expect(page.locator('.home-project')).toContainText('0 / 1 完成')
})

test('home puts Today first and keeps time distribution at the viewport bottom', async ({
  page,
}) => {
  await page.goto('/')
  await expect(
    page.locator('.home .page-head').getByRole('button', { name: '新增事项', exact: false }),
  ).toHaveCount(0)
  for (const [width, height] of [
    [1440, 880],
    [1100, 700],
    [1796, 1095],
  ]) {
    await page.setViewportSize({ width: width!, height: height! })
    const today = await page.locator('.home-columns > .today').boundingBox()
    const notes = await page.locator('.home-columns > .notes').boundingBox()
    const right = await page.locator('.home-columns > .home-right').boundingBox()
    expect(today!.x).toBeLessThan(notes!.x)
    expect(notes!.x).toBeLessThan(right!.x)
    await expect
      .poll(() =>
        page.evaluate(() => {
          const main = document.querySelector('main')!,
            chart = document.querySelector('.time-summary')!
          return Math.abs(
            chart.getBoundingClientRect().bottom -
              (main.getBoundingClientRect().bottom -
                parseFloat(getComputedStyle(main).paddingBottom)),
          )
        }),
      )
      .toBeLessThanOrEqual(2)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  }
  await page.evaluate(() => {
    ;(window as any).__TEST_SEGMENTS__ = [
      {
        id: 1,
        start: '2026-10-28T12:00:00+08:00',
        last_seen: '2026-10-28T12:20:00+08:00',
        end: '2026-10-28T12:20:00+08:00',
        seconds: 1200,
        app: 'Codex',
        process: 'Codex.exe',
        title: '测试记录',
        kind: 'activity',
        status: 'ended',
        reason: '',
        resume_reason: '',
        category: '开发',
      },
    ]
  })
  await page.getByRole('navigation').getByRole('link', { name: '项目', exact: true }).click()
  await page.getByRole('navigation').getByRole('link', { name: '今日', exact: true }).click()
  await expect(page.locator('.time-summary canvas')).toBeVisible()
  await page.setViewportSize({ width: 1100, height: 700 })
  await page.screenshot({ path: 'test-results/home-layout-1100.png' })
})

test('completed Today rows stay visible with strike-through and can hide, reopen and remove', async ({
  page,
}) => {
  await page.goto('/')
  await page.getByLabel('快捷事项').fill('完成后仍保留')
  await page.getByLabel('快捷事项').press('Enter')
  const row = page.locator('.today .task-row').filter({ hasText: '完成后仍保留' })
  const checked = page.getByRole('checkbox', { name: '完成 完成后仍保留' })
  await expect(row).toBeVisible()
  await page.evaluate(() => (window as any).__TEST_FAIL__())
  await checked.click()
  await expect(checked).not.toBeChecked()
  await checked.click()
  await expect(checked).toBeChecked()
  await expect(row).toHaveClass(/done/)
  await expect(page.locator('.today .panel-head')).toContainText('1 / 1')
  expect(
    await row.locator('.task-title > span').evaluate((e) => getComputedStyle(e).textDecorationLine),
  ).toContain('line-through')
  const snap = await page.evaluate(() => (window as any).__TEST_BRIDGE__('snapshot', {}))
  expect(Object.values(snap.records)).toHaveLength(1)
  expect((Object.values(snap.records)[0] as any).fields.status).toBe('已完成')
  await page.getByRole('checkbox', { name: '隐藏已完成' }).check()
  await expect(row).toHaveCount(0)
  await page.getByRole('checkbox', { name: '隐藏已完成' }).uncheck()
  await expect(checked).toBeChecked()
  await page.getByRole('navigation').getByRole('link', { name: '事项', exact: true }).click()
  await page.getByRole('navigation').getByRole('link', { name: '今日', exact: true }).click()
  await expect(checked).toBeChecked()
  await page.screenshot({ path: 'test-results/home-completed-1440.png' })
  await checked.click()
  await expect(checked).not.toBeChecked()
  await expect(row).not.toHaveClass(/done/)
  await checked.click()
  await row.getByRole('button', { name: '移出', exact: true }).click()
  await expect(row).toHaveCount(0)
  const after = await page.evaluate(() => (window as any).__TEST_BRIDGE__('snapshot', {}))
  expect((Object.values(after.records)[0] as any).fields.status).toBe('已完成')
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
