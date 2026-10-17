// Actual Tauri WebView2 → IPC → Rust → SQLite checks, using a disposable profile.
import { chromium, expect } from '@playwright/test'
import { spawn, spawnSync } from 'node:child_process'
import { mkdir, mkdtemp, writeFile } from 'node:fs/promises'
import { resolve, join } from 'node:path'
import net from 'node:net'
import { performance } from 'node:perf_hooks'

const root = resolve(import.meta.dirname, '..')
const installed = process.argv[2] ? resolve(process.argv[2]) : null
const binary = installed ?? resolve(root, 'src-tauri/target/debug/agent-system.exe')
await mkdir(join(root, '.test-data'), { recursive: true })
const profile = await mkdtemp(join(root, '.test-data/native-'))
const errors = []
let child, browser, page
async function freePort() {
  return new Promise((resolve) => {
    const server = net.createServer()
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address()
      server.close(() => resolve(port))
    })
  })
}
async function start() {
  const port = await freePort(),
    began = performance.now()
  child = spawn(binary, installed ? [] : ['--verify-profile', profile, '--fixed-reader'], {
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
    env: {
      ...process.env,
      ...(installed ? { LOCALAPPDATA: profile } : {}),
      ...(installed
        ? {
            PATH: `${process.env.WINDIR}\\System32;${process.env.WINDIR}`,
            PYTHONHOME: '',
            PYTHONPATH: '',
          }
        : {}),
      WEBVIEW2_USER_DATA_FOLDER: join(profile, 'webview'),
      WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: `--remote-debugging-port=${port} --remote-debugging-address=127.0.0.1`,
    },
  })
  child.stderr.on('data', () => {})
  for (let attempt = 0; attempt < 100; attempt++) {
    if (child.exitCode !== null) throw Error('Native process exited: ' + child.exitCode)
    try {
      const response = await fetch(`http://127.0.0.1:${port}/json/version`)
      if (response.ok) break
    } catch {}
    await new Promise((r) => setTimeout(r, 200))
  }
  browser = await chromium.connectOverCDP(`http://127.0.0.1:${port}`)
  for (let attempt = 0; attempt < 100; attempt++) {
    page = browser
      .contexts()
      .flatMap((c) => c.pages())
      .find((p) => !p.url().startsWith('about:'))
    if (page) break
    await new Promise((r) => setTimeout(r, 100))
  }
  if (!page) throw Error('No native app webview')
  page.on('pageerror', (e) => errors.push(e.message))
  await expect(page.getByRole('heading', { name: '今日', exact: false }).first()).toBeVisible({
    timeout: 15000,
  })
  return Math.round(performance.now() - began)
}
async function ipc(command, args = {}) {
  return page.evaluate(({ command, args }) => window.__TAURI_INTERNALS__.invoke(command, args), {
    command,
    args,
  })
}
async function close() {
  if (child && child.exitCode === null) {
    spawnSync(
      'powershell.exe',
      ['-NoProfile', '-Command', `(Get-Process -Id ${child.pid}).CloseMainWindow() | Out-Null`],
      { windowsHide: true },
    )
    let timeout
    await Promise.race([
      new Promise((resolve) => child.once('exit', resolve)),
      new Promise((_, reject) => {
        timeout = setTimeout(() => reject(Error('Native shutdown timeout')), 10000)
      }),
    ]).finally(() => clearTimeout(timeout))
  }
  try {
    await browser?.close()
  } catch {}
}
try {
  const startupMs = await start()
  expect((await ipc('snapshot')).records).toEqual({})
  expect((await ipc('capture_status')).running).toBe(false)
  expect((await ipc('sync_status')).has_token).toBe(false)
  await page.getByRole('textbox', { name: '随笔内容' }).fill('真实 Tauri 随笔')
  await page.getByRole('textbox', { name: '随笔内容' }).press('Enter')
  await expect(page.getByText('真实 Tauri 随笔', { exact: true })).toBeVisible()
  await page.getByRole('navigation').getByRole('link', { name: '项目', exact: true }).click()
  await page.getByRole('button', { name: '新建项目', exact: false }).click()
  await page.getByLabel('项目名称', { exact: true }).fill('桌面重构验收')
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.getByRole('heading', { name: '桌面重构验收', exact: false })).toBeVisible()
  await page.getByRole('button', { name: '新增阶段', exact: false }).click()
  await page.getByLabel('阶段标题').fill('第一阶段')
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.getByText('第一阶段', { exact: true })).toBeVisible()
  await page.locator('details.stage').getByRole('button', { name: '事项', exact: false }).click()
  await page.getByLabel('事项名称').fill('真实 Rust 事项')
  const day = new Date().toLocaleDateString('sv-SE')
  await page.getByLabel('开始日期', { exact: true }).fill(day)
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await page.getByRole('navigation').getByRole('link', { name: '今日', exact: true }).click()
  await expect(page.getByRole('button', { name: '真实 Rust 事项', exact: false })).toBeVisible()
  await page.getByRole('checkbox', { name: '完成 真实 Rust 事项' }).click()
  await expect(page.getByRole('button', { name: '撤销完成操作' })).toBeVisible()
  await page.getByRole('button', { name: '撤销完成操作' }).click()
  await expect(page.getByRole('checkbox', { name: '完成 真实 Rust 事项' })).not.toBeChecked()
  let snapshot = await ipc('snapshot')
  const task = Object.values(snapshot.records).find((r) => r.kind === 'tasks').fields
  expect(task.completions).toHaveLength(1)
  expect(task.completions[0].reopened_at).toBeTruthy()
  await page.getByRole('navigation').getByRole('link', { name: '求职', exact: true }).click()
  await page.getByRole('button', { name: '新增已投岗位', exact: false }).click()
  await page.getByLabel('公司', { exact: true }).fill('测试公司')
  await page.getByLabel('岗位', { exact: true }).fill('Rust 开发')
  await page.getByLabel('面试时间', { exact: true }).fill(day + ' 13:00')
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.locator('.n-data-table').getByText('面试中', { exact: true })).toBeVisible()
  await page.getByRole('navigation').getByRole('link', { name: '财务', exact: true }).click()
  await page.getByRole('button', { name: '记一笔', exact: false }).click()
  await page.getByLabel('方向', { exact: true }).selectOption('收入')
  await page.getByLabel('金额（元）', { exact: true }).fill('128.50')
  await page.getByLabel('名称', { exact: true }).fill('跨月待结算')
  await page.getByLabel('交易日期', { exact: true }).fill('2026-09-28')
  await page.getByLabel('副业来源', { exact: true }).fill('固定测试来源')
  await page.getByLabel('到账状态', { exact: true }).selectOption('待结算')
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await page.getByRole('button', { name: '待结算', exact: false }).click()
  await page.getByRole('button', { name: '确认到账', exact: true }).click()
  await page.getByLabel('实际到账金额（元）').fill('120.00')
  await page.getByLabel('实际到账日期').fill(day)
  await page.getByRole('button', { name: '确认到账', exact: true }).last().click()
  await expect(page.getByText('跨月待结算', { exact: true })).toHaveCount(0)
  snapshot = await ipc('snapshot')
  const finance = Object.values(snapshot.records).find((r) => r.kind === 'finance_entries').fields
  expect(finance.amount_cents).toBe(12000)
  expect(finance.status).toBe('已到账')
  expect(finance.occurred_on).toBe('2026-09-28')
  expect(finance.settled_on).toBe(day)
  await ipc('sync_configure', {
    settings: { auto_sync: false, check_on_start: false },
    token: 'native-test-fake-token',
    remember: true,
    forget: false,
  })
  if (!installed) {
    await ipc('capture_control', { running: true, exclusions: '' })
    await new Promise((r) => setTimeout(r, 2300))
    await ipc('capture_control', { running: false, exclusions: '' })
    await new Promise((r) => setTimeout(r, 250))
    const segments = await ipc('segments', { day })
    expect(segments.length).toBeGreaterThan(0)
    expect(segments.every((s) => s.title === '固定测试窗口')).toBe(true)
    expect(segments.reduce((a, b) => a + b.seconds, 0)).toBeGreaterThan(0)
  }
  await page.getByRole('navigation').getByRole('link', { name: '今日', exact: true }).click()
  await page.screenshot({ path: join(profile, 'home-1440.png') })
  const persisted = (await ipc('snapshot')).records
  // One working-set sample, including child WebView2 processes; not a peak or private-byte measure.
  const memoryRead = spawnSync(
    'powershell.exe',
    [
      '-NoProfile',
      '-NonInteractive',
      '-Command',
      `
    $rows = @(Get-CimInstance Win32_Process)
    $ids = @(${child.pid})
    do {
      $next = @($rows | Where-Object { $_.ParentProcessId -in $ids -and $_.ProcessId -notin $ids } | ForEach-Object { [int]$_.ProcessId })
      $ids += $next
    } while ($next.Count -gt 0)
    $own = Get-Process -Id ${child.pid}
    $all = @(Get-Process -Id $ids -ErrorAction SilentlyContinue)
    @{hostBytes=$own.WorkingSet64; treeBytes=($all | Measure-Object WorkingSet64 -Sum).Sum; processes=$all.Count} | ConvertTo-Json -Compress
  `,
    ],
    { encoding: 'utf8', windowsHide: true, timeout: 15000 },
  )
  if (memoryRead.status !== 0) throw Error('Cannot sample native working set: ' + memoryRead.stderr)
  const workingSetSample = JSON.parse(memoryRead.stdout)
  await close()
  await start()
  expect((await ipc('snapshot')).records).toEqual(persisted)
  expect((await ipc('capture_status')).running).toBe(false)
  expect((await ipc('sync_status')).has_token).toBe(true)
  await ipc('sync_configure', {
    settings: { auto_sync: false, check_on_start: false },
    token: null,
    remember: true,
    forget: true,
  })
  expect((await ipc('sync_status')).has_token).toBe(false)
  expect(errors).toEqual([])
  await close()
  const result = {
    startupMs,
    workingSetSample,
    profile,
    installedRelease: !!installed,
    captureTest: installed
      ? 'not started; fixed-reader state machine covered by Rust tests'
      : 'fixed reader',
    checks:
      'native UI → IPC → Rust → SQLite; notes, projects, stage tasks, completion undo/history, recruitment times, financial settlement, encrypted credentials, restart persistence' +
      (installed ? '' : ', fixed capture'),
    errors,
  }
  await writeFile(join(profile, 'result.json'), JSON.stringify(result, null, 2))
  console.log(JSON.stringify(result))
} finally {
  if (child?.exitCode === null) child.kill()
  try {
    await browser?.close()
  } catch {}
}
