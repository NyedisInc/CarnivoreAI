
import { normalizeStatus, tightestWindow, type Resource } from '../api';
import type {
  CatalogListResponse,
  LedgerSnapshot,
  ProjectResponse,
  RecentSessionsResponse,
  SessionInfo,
} from '../api';
import { history, KEYS } from '../api/history';
import { parseServerTime } from '../lib/format';
import { measuredRunningTotal } from '../../lib/subagents/subagents';

export { KEYS };

export interface SparkBar {
  h: number;
  tone: string;
}

export interface StatCard {
  id: string;
  icon: string;
  tone: string;
  labelKey: string;
  shortLabelKey?: string;
  key: string;
  unit: number;
  barTone: string;
  barCount: number;
  badge?: boolean;
  sparkBarWidth: number;
  sparkGap: number;
  iconSize?: number;
  iconStroke?: number;
}

export const STAT_TEXT_INSET_PX = 75;

export const SPARK_BOX_PX = 33;

const DIM = '--oc-spark-dim';
const MID = '--oc-spark-mid';
const LIT = '--oc-spark';

export const stats: StatCard[] = [
  {
    id: 'running',
    icon: 'terminal-glyph',
    tone: '--oc-stat-1',
    labelKey: 'opscenter.stat.running',
    shortLabelKey: 'opscenter.stat.short.running',
    key: KEYS.running,
    unit: 1,
    barTone: DIM,
    barCount: 6,
    sparkBarWidth: 5,
    sparkGap: 2.5,
    iconSize: 24,
    iconStroke: 2.8,
  },
  {
    id: 'sessions',
    icon: 'session',
    tone: '--oc-stat-2',
    labelKey: 'opscenter.stat.sessions_24h',
    shortLabelKey: 'opscenter.stat.short.sessions_24h',
    key: KEYS.sessions24h,
    unit: 1,
    barTone: MID,
    barCount: 6,
    badge: true,
    sparkBarWidth: 5,
    sparkGap: 2.5,
  },
  {
    id: 'projects',
    icon: 'check-bold',
    tone: '--oc-stat-3',
    labelKey: 'opscenter.stat.projects',
    shortLabelKey: 'opscenter.stat.short.projects',
    key: KEYS.projects,
    unit: 1,
    barTone: LIT,
    barCount: 6,
    sparkBarWidth: 5,
    sparkGap: 2.5,
    iconSize: 24,
    iconStroke: 3.2,
  },
  {
    id: 'ledger',
    icon: 'arrow-down-circle',
    tone: '--oc-stat-4',
    labelKey: 'opscenter.stat.ledger',
    shortLabelKey: 'opscenter.stat.short.ledger',
    key: KEYS.ledger,
    unit: SPARK_BOX_PX / 100,
    barTone: LIT,
    barCount: 6,
    sparkBarWidth: 5,
    sparkGap: 2.5,
    iconSize: 24,
    iconStroke: 2.2,
  },
  {
    id: 'alive',
    icon: 'person-bust',
    tone: '--oc-stat-5',
    labelKey: 'opscenter.stat.alive',
    shortLabelKey: 'opscenter.stat.short.alive',
    key: KEYS.alive,
    unit: 1,
    barTone: LIT,
    barCount: 5,
    sparkBarWidth: 6.5,
    sparkGap: 4,
    iconSize: 24,
    iconStroke: 2,
  },
  {
    id: 'subagents',
    icon: 'users',
    tone: '--oc-stat-2',
    labelKey: 'opscenter.stat.subagents',
    shortLabelKey: 'opscenter.stat.short.subagents',
    key: KEYS.subagents,
    unit: 1,
    barTone: MID,
    barCount: 6,
    sparkBarWidth: 5,
    sparkGap: 2.5,
    iconSize: 22,
    iconStroke: 2,
  },
];

const DAY_MS = 24 * 60 * 60 * 1000;

/* could not be determined */
export interface Figure {
  value: number | null;
  status: string;
  message: string;
}

export interface Figures {
  running: Figure;
  sessions24h: Figure;
  projects: Figure;
  ledger: Figure;
  alive: Figure;
  subagentsRunning: Figure;
  total: number | null;
  skills: Figure;
  ledgerResetSeconds: number | null;
  detail: FigureDetail;
}

export interface FigureDetail {
  liveRows: number | null;
  closed24h: number | null;
  projectsWithLive: number | null;
  subagentParents: number | null;
}

export interface FigureSources {
  sessions: Resource<SessionInfo[]>;
  recent: Resource<RecentSessionsResponse>;
  projects: Resource<ProjectResponse[]>;
  catalog: Resource<CatalogListResponse>;
  ledger: Resource<LedgerSnapshot>;
}

/* could not be determined */
function absent(status: string, message: string | null = null): Figure {
  return { value: null, status, message: message ?? '' };
}


/* could not look */
export function deriveFigures(sources: FigureSources, now = Date.now()): Figures {
  const rows = sources.sessions.status === 'ok' ? (sources.sessions.data ?? []) : null;
  const sessionStatus = sources.sessions.status;
  const sessionMessage = sources.sessions.error ?? '';

  const running: Figure = rows
    ? {
        value: rows.filter((row) => {
          const key = normalizeStatus(row.activity_status);
          return key === 'working' || key === 'working_subagent' || key === 'running';
        }).length,
        status: 'ok',
        message: '',
      }
    : absent(sessionStatus, sessionMessage);

  const aliveCount = rows
    ? rows.filter((row) => {
        const key = normalizeStatus(row.activity_status);
        return key !== 'dead' && key !== 'stopped';
      }).length
    : null;
  const alive: Figure = aliveCount === null ? absent(sessionStatus, sessionMessage) : { value: aliveCount, status: 'ok', message: '' };

  const subagentsTotal = rows ? measuredRunningTotal(rows) : null;
  const subagentsRunning: Figure =
    subagentsTotal === null ? absent('unmeasured') : { value: subagentsTotal, status: 'ok', message: '' };

  let sessions24h: Figure;
  let closed24h: number | null = null;
  if (!rows) {
    sessions24h = absent(sessionStatus, sessionMessage);
  } else if (sources.recent.status !== 'ok') {
    sessions24h = absent(sources.recent.status, sources.recent.error ?? '');
  } else {
    const answer = sources.recent.data;
    const state = answer?.state ?? 'never_probed';
    if (state !== 'ok') {
      sessions24h = absent('could-not-determine', state);
    } else {
      const closed = (answer?.sessions ?? []).filter((record) => {
        if (!record.created_at) return false;
        const at = parseServerTime(record.created_at);
        return Number.isFinite(at) && now - at <= DAY_MS;
      }).length;
      closed24h = closed;
      sessions24h = { value: rows.length + closed, status: 'ok', message: '' };
    }
  }

  const projects: Figure =
    sources.projects.status === 'ok'
      ? { value: (sources.projects.data ?? []).length, status: 'ok', message: '' }
      : absent(sources.projects.status, sources.projects.error ?? '');

  const skills: Figure =
    sources.catalog.status === 'ok'
      ? {
          value: (sources.catalog.data?.items ?? []).filter((item) => item.kind === 'skill' && item.installed !== null).length,
          status: 'ok',
          message: '',
        }
      : absent(sources.catalog.status, sources.catalog.error ?? '');

  let ledger: Figure;
  let ledgerResetSeconds: number | null = null;
  if (sources.ledger.status !== 'ok') {
    ledger = absent(sources.ledger.status, sources.ledger.error ?? '');
  } else if (!sources.ledger.data?.total.accounts) {
    ledger = absent('no-accounts');
  } else {
    const window = sources.ledger.data ? tightestWindow(sources.ledger.data.total) : null;
    if (!window) {
      ledger = absent('not-reported');
    } else {
      ledger = { value: Math.round(window.used_pct), status: 'ok', message: '' };
      if (window.resets_at) {
        const at = parseServerTime(window.resets_at);
        if (Number.isFinite(at)) ledgerResetSeconds = Math.max(0, Math.round((at - now) / 1000));
      }
    }
  }

  return {
    running,
    sessions24h,
    projects,
    ledger,
    alive,
    subagentsRunning,
    total: rows ? rows.length : null,
    skills,
    ledgerResetSeconds,
    detail: {
      liveRows: rows ? rows.length : null,
      closed24h,
      projectsWithLive: rows && sources.projects.status === 'ok' ? countProjectsWithLive(rows, sources.projects.data ?? []) : null,
      subagentParents: rows && subagentsTotal !== null
        ? rows.filter((row) => row.subagents_state === 'ok' && (row.subagents_running ?? 0) > 0).length
        : null,
    },
  };
}

/* could not be determined */
export function sampleFigures(figures: Figures, sources: FigureSources): void {
  const atSessions = sources.sessions.fetchedAt;
  history.sample(KEYS.running, figures.running.value, atSessions);
  history.sample(KEYS.alive, figures.alive.value, atSessions);
  history.sample(KEYS.sessions24h, figures.sessions24h.value, atSessions);
  history.sample(KEYS.projects, figures.projects.value, sources.projects.fetchedAt);
  history.sample(KEYS.ledger, figures.ledger.value, sources.ledger.fetchedAt);
  history.sample(KEYS.skills, figures.skills.value, sources.catalog.fetchedAt);
  history.sample(KEYS.subagents, figures.subagentsRunning.value, atSessions);
}

function countProjectsWithLive(rows: readonly SessionInfo[], known: readonly ProjectResponse[]): number {
  const ids = new Set(known.map((project) => project.id));
  const live = new Set<number>();
  for (const row of rows) {
    const key = normalizeStatus(row.activity_status);
    if (key === 'dead' || key === 'stopped') continue;
    if (typeof row.project_id === 'number' && ids.has(row.project_id)) live.add(row.project_id);
  }
  return live.size;
}
