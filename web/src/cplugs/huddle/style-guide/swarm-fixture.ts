import type { PanelAgent } from '../swarm/panel-state';
import type { FloorSession } from '../../sdk';

export const NOW = 1_800_000_000_000;
export const mk = (id: number, display_name: string, rank: string, over: Partial<PanelAgent> = {}): PanelAgent =>
  ({ id, display_name, rank, state: 'awake', thread_key: `agent:${id}`, session_id: `sg_${id}`, harness: 'claude', job: `${display_name} job`, effort: 'medium', ...over });
export const AGENTS: PanelAgent[] = [
  mk(1, 'Alpha', 'alpha', { thread_key: 'all' }),
  mk(2, 'acme', 'company', { thread_key: 'company:1', company_id: 1 }),
  mk(3, 'Nyedis', 'company', { thread_key: 'company:2', company_id: 2, question_waiting: true }),
  mk(4, 'Carnivore', 'company', { thread_key: 'company:3', company_id: 3, harness: 'codex' }),
  mk(5, 'cloudecode', 'project', { thread_key: '1', project_id: 1 }),
  mk(6, 'orchard-docs', 'project', { thread_key: '2', project_id: 2 }),
  mk(7, 'portal', 'project', { thread_key: '3', project_id: 3, alert: 'priority' }),
  mk(8, 'coffee-site', 'project', { thread_key: '4', project_id: 4, harness: 'codex' }),
  mk(9, 'analytics', 'project', { thread_key: '5', project_id: 5, state: 'asleep', session_id: null }),
  mk(10, 'Dormont (galcrest ravstone)', 'task', { parent_id: 5 }),
  mk(11, 'Rook (drawer polish)', 'task', { parent_id: 5 }),
  mk(12, 'Tully (migrations)', 'feature', { activity: 'talking', activity_at: NOW / 1000, talking_with: 13 }),
  mk(13, 'Ivy (schema review)', 'feature', { activity: 'talking', activity_at: NOW / 1000, talking_with: 12, harness: 'codex' }),
  mk(14, 'Wren (seo audit)', 'task'),
  ];
export const ROWS: Record<string, { activity_status: string; startup_gate?: string; running_context_used_pct?: number; working_on?: string; working_on_state?: string }> = {
  sg_1: { activity_status: 'working_subagent', running_context_used_pct: 38, working_on: 'routing 2 requests to company agents', working_on_state: 'ok' },
  sg_2: { activity_status: 'working', running_context_used_pct: 41, working_on: 'weekly digest across 4 projects', working_on_state: 'ok' },
  sg_3: { activity_status: 'idle', running_context_used_pct: 58, working_on: 'asking which account bills the new site', working_on_state: 'ok' },
  sg_4: { activity_status: 'idle', running_context_used_pct: 12, working_on: 'nothing queued', working_on_state: 'ok' },
  sg_5: { activity_status: 'working_subagent', running_context_used_pct: 67, working_on: '2 task agents on the swarm panel', working_on_state: 'ok' },
  sg_6: { activity_status: 'finished_unread', running_context_used_pct: 34, working_on: 'docs portal redeploy done', working_on_state: 'ok' },
  sg_7: { activity_status: 'working', running_context_used_pct: 88, working_on: 'deploy check failed twice', working_on_state: 'ok' },
  sg_8: { activity_status: 'notice', running_context_used_pct: 48, working_on: 'wants a look at the menu photos', working_on_state: 'ok' },
  sg_10: { activity_status: 'working', running_context_used_pct: 72, working_on: 'swapping the model picker', working_on_state: 'ok' },
  sg_11: { activity_status: 'question', running_context_used_pct: 81, working_on: 'which login should the refresh job use?', working_on_state: 'ok' },
  sg_12: { activity_status: 'working', running_context_used_pct: 62, working_on: 'comparing notes with Ivy', working_on_state: 'ok' },
  sg_13: { activity_status: 'working', running_context_used_pct: 47, working_on: 'comparing notes with Tully', working_on_state: 'ok' },
  sg_14: { activity_status: 'idle', startup_gate: 'awaiting_startup_prompt', running_context_used_pct: 0, working_on: 'waiting on folder trust', working_on_state: 'ok' },
  };
export const ses = (key: string, label: string, projectId: number | null, status: string, over: Partial<FloorSession> = {}): FloorSession => ({
  key, name: `cloude_${key}`, label, sessionId: `sg_s_${key}`, sessionUuid: `uuid-${key}`, sessionRowId: null, asleep: false, projectId, projectName: null,
  harness: 'claude', listing: { activity_status: status, running_context_used_pct: 30 }, ...over,
  });
export const SESSIONS: FloorSession[] = [
  ses('web', 'site copy pass', 4, 'working'),
  ses('far', 'laptop: nightly job', 6, 'working', { sessionId: 'remote:peer-a:ses_far' }),
  ses('shell', 'review the diff', 2, 'finished_unread', { harness: 'codex' }),
  ses('dead', 'crashed run', 7, 'dead'),
  ses('nap', 'old spike', 7, 'asleep', { sessionId: null, asleep: true, listing: { activity_status: 'asleep' } }),
  ];
export const COMPANIES = [{ id: 1, name: 'acme' }, { id: 2, name: 'Nyedis' }, { id: 3, name: 'Carnivore' }, { id: 4, name: 'Side Projects' }];
export const PROJECTS = [
  { id: 1, name: 'cloudecode', companyId: 3 }, { id: 2, name: 'orchard-docs', companyId: 2 }, { id: 3, name: 'portal', companyId: 2 },
  { id: 4, name: 'coffee-site', companyId: 1 }, { id: 5, name: 'analytics', companyId: 2 }, { id: 6, name: 'nightly', companyId: null },
  { id: 7, name: 'spike', companyId: null },
  ];
export const rowOf = (id: string | null | undefined) => (id ? ROWS[id] : undefined);
