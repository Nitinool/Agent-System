// Fixed V2 schema-1 fixture for installed migration checks; never reads user data.
import { mkdir, readdir } from 'node:fs/promises'
import { join } from 'node:path'
import { expect } from '@playwright/test'
const p = 'a'.repeat(32),
  s = 'b'.repeat(32),
  t = 'c'.repeat(32),
  j = 'd'.repeat(32)
const job = {
  company: '旧库保留公司',
  title: '历史岗位',
  applied_on: '2026-10-16',
  status: '面试中',
  url: '',
  notes: '原求职备注',
  interview_at: '2026-10-18 13:00',
  written_at: '',
  rejected_at: '',
}
export async function seedLegacy(profile) {
  const { DatabaseSync } = await import('node:sqlite')
  const folder = join(profile, 'Agent-System-V2')
  await mkdir(folder, { recursive: true })
  const db = new DatabaseSync(join(folder, 'activity.sqlite3'))
  db.exec(`CREATE TABLE records(local_id INTEGER PRIMARY KEY,uid TEXT NOT NULL UNIQUE,kind TEXT NOT NULL,payload TEXT NOT NULL);
    CREATE TABLE state(key TEXT PRIMARY KEY,value TEXT NOT NULL);
    INSERT INTO state VALUES('revision','0'),('baseline','{}');
    CREATE TABLE segments(id INTEGER PRIMARY KEY,start TEXT NOT NULL,last_seen TEXT NOT NULL,end TEXT,seconds REAL NOT NULL CHECK(seconds>=0),app TEXT NOT NULL,process TEXT NOT NULL,title TEXT NOT NULL,kind TEXT NOT NULL,status TEXT NOT NULL,reason TEXT NOT NULL,resume_reason TEXT NOT NULL,category TEXT NOT NULL);
    PRAGMA user_version=1;`)
  const rows = {
    [p]: {
      kind: 'projects',
      fields: { name: '已有项目', goal: '', status: '进行中', priority: '普通', mode: '目标型' },
    },
    [s]: {
      kind: 'milestones',
      fields: {
        project_id: p,
        name: '未来想法',
        acceptance: '保留旧阶段内容',
        position: 1,
        completed_at: null,
      },
    },
    [t]: {
      kind: 'tasks',
      fields: {
        title: '旧事项',
        planned_on: null,
        range_start: null,
        range_end: null,
        category: '学习',
        notes: '保留旧事项',
        status: '已完成',
        priority: '普通',
        kind: '任务',
        project_id: p,
        milestone_id: null,
        resume_status: '待开始',
        acceptance: '',
        outcome: '',
        completed_at: '2026-10-16T12:00:00+08:00',
        days: [],
        excluded_days: [],
        completions: [
          {
            title: '旧事项',
            project_id: p,
            completed_at: '2026-10-16T12:00:00+08:00',
            reopened_at: null,
          },
        ],
      },
    },
    [j]: { kind: 'job_applications', fields: job },
  }
  const insert = db.prepare('INSERT INTO records(uid,kind,payload) VALUES(?,?,?)')
  for (const [id, r] of Object.entries(rows)) insert.run(id, r.kind, JSON.stringify(r))
  db.prepare("UPDATE state SET value=? WHERE key='baseline'").run(JSON.stringify(rows))
  db.close()
}
export async function verifyLegacy(records, profile) {
  expect(records[j].fields).toEqual(job)
  expect(records[p].fields.category).toBe('其他')
  expect(records[t].fields.category).toBe('学习')
  expect(records[t].fields.notes).toBe('保留旧事项')
  expect(records[t].fields.completions).toHaveLength(1)
  expect(records[s].fields).toBeNull()
  const ideas = records[records[t].fields.milestone_id]
  expect(ideas.fields.stage_kind).toBe('ideas')
  expect(ideas.fields.acceptance).toBe('保留旧阶段内容')
  expect(
    (await readdir(join(profile, 'Agent-System-V2/backups'))).filter((n) =>
      n.startsWith('before-upgrade-v1-v2-'),
    ),
  ).toHaveLength(1)
}
