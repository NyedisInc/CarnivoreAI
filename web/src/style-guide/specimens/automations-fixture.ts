import type { Automation, ProjectChoice, RunCounts, SessionChoice, Targets } from '../../lib/automations/api';
import type { FeedRun } from '../../lib/automations/logic/types';
import type { HuddleItem } from '../../cplugs/huddle/huddle-model';
import type { TaskManagerSchedule } from '../../lib/task-manager-schedules/task-manager-scheduled';

export const nowSec = (): number => Math.floor(Date.now() / 1000);

const run = (n: number, status: string, ago: number) => ({
  run_id: `r${n}`, number: n, status, reason: null, trigger: 'schedule', attempt: null, slot_at: nowSec() - ago, started_at: nowSec() - ago,
  ended_at: nowSec() - ago + 2, skip_count: null, report_bytes: 40, output_empty: false,
});

const base = {
  trigger: { cron: '0 9 * * *', timezone: 'UTC' }, delivery: { notify: true, notify_on: null }, revision: 1, last_run: null,
  description: '', project_id: null, misfire: 'run_once', retry_max: 0, retry_backoff_s: 300, max_runtime_s: null, retry_due_at: null,
  files_under: { session_uuid: null, project_id: null }, created_by: 'app', updated_by: 'app', created_at: nowSec() - 9000, updated_at: nowSec() - 100,
  created_actor: { kind: 'app' }, updated_actor: { kind: 'app' }, spends: false,
};

export function fixtureAutomations(): Automation[] {
  const recent = Array.from({ length: 12 }, (_, i) => run(12 - i, 'succeeded', 900 * (i + 1) - 300));
  return [
    {
      ...base, automation_id: 'aut_scrooge', name: 'harbor willow', enabled: false, trigger: { cron: '0 9 * * *', timezone: 'UTC' },
      next_fire_at: null, target: { kind: 'recipe', recipe: 'scrooge', params: {} }, recent: [], median_took_s: null, newest_output_empty: false,
      run_count: 0, newest_number: null, spends: true,
    },
    {
      ...base, automation_id: 'aut_backup', name: 'backup health check', enabled: true, next_fire_at: nowSec() + 600,
      target: { kind: 'command', command: '/usr/bin/backup-check' }, recent, median_took_s: 2, newest_output_empty: false, run_count: 12, newest_number: 12,
    },
  ] as Automation[];
}

export function fixtureCounts(): RunCounts {
  const ids = ['succeeded_24h', 'failed_24h', 'succeeded_7d', 'failed_7d', 'skipped_7d', 'produced_nothing_7d', 'running', 'waiting_on_you'];
  const figures = [96, 0, 200, 0, 0, 0, 0, 0];
  return {
    now: nowSec(), hosts: [], has_unrecorded_host: false, next_change_at: null,
    counters: Object.fromEntries(ids.map((id, i) => [id, { count: figures[i], automation_ids: [] }])),
  } as unknown as RunCounts;
}

export const fixtureProjects: ProjectChoice[] = [
  { id: 1, name: 'meadow harbor', folder: '/x/meadow' },
  { id: 2, name: 'pebble meadow', folder: '/x/notes' },
  { id: 3, name: 'lantern harbor', folder: '/x/willow' },
];

export const fixtureSessions: SessionChoice[] = [
  { id: 1, session_uuid: 'u-meadow', label: 'meadow pebble', name: 'meadow pebble', lifecycle: 'running', project_id: 1 },
  { id: 2, session_uuid: 'u-notes', label: 'pebble meadow', name: 'pebble meadow', lifecycle: 'running', project_id: 2 },
  { id: 3, session_uuid: 'u-willow', label: 'lantern harbor', name: 'lantern harbor', lifecycle: 'running', project_id: 3 },
];

const hour = 3600;
const item = (id: number, title: string, inHours: number, sessionKey: string, projectId: number, repeat: TaskManagerSchedule['repeat'], over: Partial<TaskManagerSchedule> = {}): TaskManagerSchedule => ({
  list: 'main', item: id, title, fireAt: nowSec() + inHours * hour, paused: false, state: 'pending', sessionKey, projectId, repeat, source: { id, revision: 1 } as unknown as HuddleItem, ...over,
});

export function fixtureSchedules(): TaskManagerSchedule[] {
  return [
    item(1, 'clean up stale branches and temp folders', 120, 'u-meadow', 1, null),
    item(2, 'verify the backup finished and is readable', 120.1, 'u-meadow', 1, null),
    item(3, 'prepare the release notes for the next build', 5, 'u-notes', 2, { freq: 'daily', time: '08:00' }),
    item(4, 'rotate the staging credentials after the freeze ends', 170, 'u-notes', 2, null),
    item(5, 'check the nightly sync and report gaps', 7, 'u-willow', 3, { freq: 'daily', time: '09:15' }),
    item(6, 'check the nightly sync and report gaps', 9, 'u-willow', 3, { freq: 'weekly', time: '18:45', byweekday: [1] }),
    item(7, 'check the nightly sync and report gaps', 3, 'u-willow', 3, { freq: 'hourly', interval: 6 }),
    item(8, 'update the onboarding checklist', 0, 'u-willow', 3, { freq: 'daily', time: '14:20' }, { paused: true }),
  ];
}

export function fixtureTargets(): Targets {
  return {
    kinds: ['recipe', 'command', 'sequence', 'session_message', 'agent', 'blueprint_launch', 'card'],
    commands: ['/usr/bin/backup-check'],
    recipes: [{ recipe: 'scrooge', params_schema: { properties: { active_days: { type: 'integer', default: 30, minimum: 1, maximum: 90 } } } }],
  } as unknown as Targets;
}

const FAILED_REPORT = {
  summary: 'volume 3 did not answer; the other 13 are healthy',
  exit_code: 1,
  stderr: 'ping: timeout\nretrying\nping: timeout',
  checked: 14,
  healthy: 13,
  failed: 1,
  items: [{ label: 'volume 1', status: 'ok', detail: '412 GB free' }, { label: 'volume 3', status: 'fail', detail: 'no answer in 30 s' }],
  volumes: { v1: { free_gb: 412, state: 'ok' }, v2: { free_gb: 88, state: 'ok' }, v3: { free_gb: 0, state: 'fail' } },
  details: { host: { name: 'nas', zone: 'home' }, history: [{ day: 'mon', ok: true }, { day: 'tue', ok: false }] },
};

export function fixtureFeed(): FeedRun[] {
  const row = (n: number, name: string, id: string, status: string, ago: number, summary: string, report?: Record<string, unknown>): FeedRun => ({
    run_id: `${id}-${n}`, automation_id: id, automation_name: name, number: n, status, reason: null, trigger: 'schedule', attempt: null,
    slot_at: nowSec() - ago, started_at: nowSec() - ago, ended_at: nowSec() - ago + 2, skip_count: null, first_slot_at: null, last_slot_at: null,
    report_bytes: 40, output_empty: false, has_report: true, error: status === 'failed' ? 'exit 1' : null, cost_usd: null, host: null,
    usage: null, delivered: null, attachments: null, sessions: [], report: report ?? { summary },
  }) as unknown as FeedRun;
  return [
    row(12, 'backup health check', 'aut_backup', 'succeeded', 300, 'all 14 volumes healthy'),
    row(11, 'backup health check', 'aut_backup', 'failed', 1200, 'volume 3 did not answer', FAILED_REPORT),
    row(10, 'backup health check', 'aut_backup', 'succeeded', 2100, 'all 14 volumes healthy'),
    row(3, 'scrooge weekly', 'aut_scrooge', 'succeeded', 90000, 'spent 4.20 this week'),
  ];
}
