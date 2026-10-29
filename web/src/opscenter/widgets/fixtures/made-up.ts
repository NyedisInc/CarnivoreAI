import type { ProjectResponse, SessionInfo, SessionRecord } from '../../api/types';
import type { AttachableSession } from '../../../lib/sessions/types';
import { ago, DAY, epochAgo, HOUR, MIN } from './clock';

export const TERMINAL_ROW_ID = 9001;

export interface MadeUpProject {
  id: number;
  name: string;
  path: string;
  description: string;
}

export const PROJECTS: readonly MadeUpProject[] = [
  { id: 1, name: 'billing-api', path: '/work/billing-api', description: 'invoices, plans and the payment webhooks' },
  { id: 2, name: 'docs-site', path: '/work/docs-site', description: 'the public documentation site' },
  { id: 3, name: 'mobile-app', path: '/work/mobile-app', description: 'the phone client' },
  { id: 4, name: 'infra-tools', path: '/work/infra-tools', description: 'deploy scripts and monitors' },
];

export function projectList(): ProjectResponse[] {
  return PROJECTS.map((project, index): ProjectResponse => ({
    id: project.id,
    name: project.name,
    path: project.path,
    description: project.description,
    root: project.path,
    work_at: ago((index + 1) * 40 * MIN),
    archived_at: null,
  }));
}

interface SessionSeed {
  tmux: string;
  label: string;
  project: MadeUpProject;
  status: string;
  unread: boolean;
  agent: 'claude' | 'codex';
  model: string;
  startedAgo: number;
  activeAgo: number;
  rowId: number;
  theme: string | null;
}

const SESSIONS: readonly SessionSeed[] = [
  { tmux: 'cloude_billing-api', label: 'billing-api', project: PROJECTS[0]!, status: 'working', unread: false, agent: 'claude', model: 'opus 5.5', startedAgo: 3 * HOUR, activeAgo: 20, rowId: TERMINAL_ROW_ID, theme: 'amber-terminal' },
  { tmux: 'cloude_docs-site', label: 'docs-site', project: PROJECTS[1]!, status: 'question', unread: false, agent: 'claude', model: 'sonnet 5.5', startedAgo: 5 * HOUR, activeAgo: 4 * MIN, rowId: 9002, theme: null },
  { tmux: 'cloude_mobile-app', label: 'mobile-app', project: PROJECTS[2]!, status: 'finished_unread', unread: true, agent: 'claude', model: 'sonnet 5.5', startedAgo: DAY, activeAgo: 18 * MIN, rowId: 9003, theme: null },
  { tmux: 'cloude_infra-tools', label: 'infra-tools', project: PROJECTS[3]!, status: 'idle', unread: false, agent: 'codex', model: 'gpt 5.2', startedAgo: 2 * DAY, activeAgo: 2 * HOUR, rowId: 9004, theme: null },
  { tmux: 'cloude_billing-webhooks', label: 'billing webhooks', project: PROJECTS[0]!, status: 'working_subagent', unread: false, agent: 'claude', model: 'opus 5.5', startedAgo: 90 * MIN, activeAgo: 45, rowId: 9005, theme: null },
];

export const SESSION_NAMES: readonly string[] = SESSIONS.map((seed) => seed.tmux);

function sessionInfo(seed: SessionSeed): SessionInfo {
  return {
    session: {
      id: `ses_${seed.tmux.replace('cloude_', '').replace(/-/g, '')}`,
      pty_pid: null,
      working_dir: seed.project.path,
      status: 'active',
      created_at: ago(seed.startedAgo),
      last_activity: ago(seed.activeAgo),
      agent_type: seed.agent,
      pinned_theme: seed.theme,
      tmux_session: seed.tmux,
      model: seed.model,
      tmux_created_epoch: null,
    },
    recent_logs: [],
    stats: { total_commands: 14, uptime_seconds: seed.startedAgo, log_lines: 320, local_servers: 0 },
    session_backend: 'tmux',
    tmux_session: seed.tmux,
    label: seed.label,
    agent_type: seed.agent,
    agent_family: seed.agent,
    agent_family_source: 'launch',
    agent_wrapper_label: null,
    pinned_theme: seed.theme,
    activity_status: seed.status,
    activity_hint: null,
    unread: seed.unread,
    startup_gate: null,
    status_source: 'registry',
    project_id: seed.project.id,
    project_name: seed.project.name,
    session_row_id: seed.rowId,
    subagents_running: seed.status === 'working_subagent' ? 2 : 0,
    subagents_total: seed.status === 'working_subagent' ? 3 : 0,
    background_open: 0,
  };
}

export function sessionList(): SessionInfo[] {
  return SESSIONS.map(sessionInfo);
}

function record(uuid: string, title: string, project: MadeUpProject, agent: string, lastAgo: number, extra: Partial<SessionRecord>): SessionRecord {
  return {
    session_uuid: uuid,
    origin: 'created',
    owned: true,
    lifecycle: 'stopped',
    title,
    working_dir: project.path,
    agent_type: agent,
    agent_family: agent,
    archived_at: null,
    created_at: ago(lastAgo + 2 * HOUR),
    last_work_at: ago(lastAgo),
    project_id: project.id,
    tmux_name: `cloude_${title.replace(/\s+/g, '-')}`,
    closed_at: ago(lastAgo),
    closed_basis: 'closed',
    asleep: false,
    unread: false,
    id: null,
    tmux_created_epoch: null,
    ...extra,
  };
}

export function recentRecords(): SessionRecord[] {
  return [
    record('6d1f0c52-8a3e-4b1d-9c47-2e5a7b90d101', 'billing retries', PROJECTS[0]!, 'claude', 35 * MIN, {}),
    record('6d1f0c52-8a3e-4b1d-9c47-2e5a7b90d102', 'docs search', PROJECTS[1]!, 'claude', 3 * HOUR, {}),
    record('6d1f0c52-8a3e-4b1d-9c47-2e5a7b90d103', 'push tokens', PROJECTS[2]!, 'codex', 9 * HOUR, {}),
    record('6d1f0c52-8a3e-4b1d-9c47-2e5a7b90d104', 'backup monitor', PROJECTS[3]!, 'claude', DAY, {}),
    record('6d1f0c52-8a3e-4b1d-9c47-2e5a7b90d105', 'old invoice export', PROJECTS[0]!, 'claude', 4 * DAY, { archived_at: ago(2 * DAY) }),
  ];
}

export function asleepRecords(): SessionRecord[] {
  return [
    record('6d1f0c52-8a3e-4b1d-9c47-2e5a7b90d201', 'release notes', PROJECTS[1]!, 'claude', 6 * HOUR, { asleep: true }),
    record('6d1f0c52-8a3e-4b1d-9c47-2e5a7b90d202', 'onboarding flow', PROJECTS[2]!, 'claude', 11 * HOUR, { asleep: true }),
  ];
}

function liveUuid(seed: SessionSeed): string {
  return `6d1f0c52-8a3e-4b1d-9c47-2e5a7b90${String(seed.rowId).padStart(4, '0')}`;
}

export function attachableRows(): AttachableSession[] {
  return SESSIONS.map((seed): AttachableSession => ({
    name: seed.tmux,
    label: seed.label,
    created_by_cloude: true,
    created_by_us: true,
    created_at_epoch: epochAgo(seed.startedAgo),
    window_count: 1,
    agent_type: seed.agent,
    agent_family: seed.agent,
    agent_family_source: 'launch',
    agent_wrapper_label: null,
    pinned_theme: seed.theme,
    status: seed.status === 'working' || seed.status === 'working_subagent' ? 'running' : 'idle',
  }));
}

export function liveRecords(): SessionRecord[] {
  const live = SESSIONS.map((seed) => record(liveUuid(seed), seed.label, seed.project, seed.agent, seed.activeAgo, {
    lifecycle: 'running', tmux_name: seed.tmux, closed_at: null, closed_basis: null, id: seed.rowId, unread: seed.unread,
    created_at: ago(seed.startedAgo), tmux_created_epoch: epochAgo(seed.startedAgo),
  }));
  return [...live, ...asleepRecords(), ...recentRecords()];
}

export function companionList(): SessionInfo[] {
  const seed = SESSIONS[0]!;
  const info = sessionInfo(seed);
  return [{
    ...info,
    session: { ...info.session, id: 'ses_billingapish', tmux_session: `${seed.tmux}_sh`, agent_type: 'shell' },
    tmux_session: `${seed.tmux}_sh`,
    label: 'billing-api shell',
    agent_type: 'shell',
    agent_family: 'shell',
    activity_status: 'idle',
    session_row_id: 9101,
  }];
}
