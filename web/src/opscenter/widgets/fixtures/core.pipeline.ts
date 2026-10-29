import { epochAgo, HOUR, MIN } from './clock';
import type { WidgetFixtures } from './types';

const MACHINE = { scope: 'machine', session_uuid: null, session: null, project_id: null, project: null, conversation: null };
const SESSION = { scope: 'session', session_uuid: '8f1c2d3e-4a5b-4c6d-8e7f-9a0b1c2d3e4f', session: 'billing-api', project_id: 1, project: 'billing-api', conversation: null };
const PROJECT = { scope: 'project', session_uuid: null, session: null, project_id: 2, project: 'docs-site', conversation: null };

function recent(plugin: string, area: object, finishedAgo: number, durationMs: number, runs: number, outcome: 'ok' | 'failed' | 'parked', error: string | null = null): unknown {
  return {
    plugin, contributor: null, kind: 'delivery', ...area, conversation_id: null, family: 'claude', trigger: 'live', finished_at: epochAgo(finishedAgo),
    duration_ms: durationMs, runs, events: 24, outcome, error,
  };
}

const PLUGIN_STATUS = { lag: { files: 0, seconds: 0 }, failures: 0, last_error: null, rebuilding: false, last_delivery_at: epochAgo(4 * MIN), runs: 31 };

const BEHIND = {
  state: 'behind',
  lag: { files: 3, seconds: 95 },
  last_delivery_at: epochAgo(4 * MIN),
  stalled_since: null,
  rebuilding: [],
  plugins: {
    stats: PLUGIN_STATUS,
    deepsearch: { ...PLUGIN_STATUS, lag: { files: 3, seconds: 95 }, failures: 1, last_error: 'KeyError' },
    backups: PLUGIN_STATUS,
  },
  recent: [
    recent('stats', SESSION, 40, 180, 31, 'ok'),
    recent('deepsearch', PROJECT, 3 * MIN, 2400, 12, 'failed', 'KeyError'),
    recent('backups', MACHINE, 25 * MIN, 5200, 4, 'ok'),
    recent('stats', MACHINE, HOUR, 900, 2, 'parked', 'timeout'),
  ],
  running: [{ plugin: 'deepsearch', kind: 'delivery', ...SESSION, family: 'claude', trigger: 'live', started_at: epochAgo(6), running_s: 6 }],
  queue: {
    items: [
      { plugins: [], ...PROJECT, family: 'claude', trigger: 'plugins', backoff: false, marked_at: epochAgo(70), waited_s: 70, due_at: null },
      { plugins: ['deepsearch'], ...MACHINE, conversation: 'c0ffee12', family: 'claude', trigger: 'live', backoff: true, marked_at: epochAgo(4 * MIN), waited_s: 240, due_at: epochAgo(-90) },
    ],
    total: 2,
  },
};

const CAUGHT_UP = {
  state: 'caught_up',
  lag: { files: 0, seconds: 0 },
  last_delivery_at: null,
  stalled_since: null,
  rebuilding: [],
  plugins: {},
  recent: [],
  running: [],
  queue: { items: [], total: 0 },
};

export const pipelineFixtures: WidgetFixtures = {
  data: { 'GET /pipeline/status': BEHIND },
  empty: { 'GET /pipeline/status': CAUGHT_UP },
};
