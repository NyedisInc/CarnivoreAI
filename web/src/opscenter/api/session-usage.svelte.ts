
import { authFetch } from './auth.svelte';
import { resource, type Resource } from './poll.svelte';
import type { SessionTokenUsage } from './types';
import { t } from '../../lib/i18n/index.svelte';
import {
  usagePanelLabels,
  scaleStep,
  scaleStepFor,
  SCALE_STOPS,
  WINDOW_SCALE_STOPS,
  USAGE_PANEL_KEYS,
} from '../../../../client/js/labels/usage-panel.js';

export const SESSION_USAGE_POLL_MS = 30000;

export interface UsageMeter {
  segments: number;
  filled: number;
  scale: number | null;
  percentText: string;
  meterText: string;
}

export interface UsageContextView extends UsageMeter {
  title: string;
  captionLabel: string;
  detail: string;
  compactDetail: string;
}

export interface UsageWindowView extends UsageMeter {
  key: string;
  label: string;
  labelText: string;
  /** "reset in 1h 5m", or the undetermined sentence - for a caller with no
   *  icon of its own (the ledger drawer). Never a clock date, even a day
   *  or more out. */
  resetText: string;
  resetDuration: string;
  resetAria: string;
  paceElapsedPct: number | null;
  paceState: 'on' | 'ahead' | 'over' | null;
}

export interface UsageRow {
  key: string;
  label: string;
  text: string;
  spans?: Array<{ text: string; tier?: number | null; title?: string }>;
  parts?: { lead: string; dim: string } | null;
}

export type UsagePanelModel =
  | { state: 'absent' | 'unchecked'; title: string; message: string }
  | {
      state: 'ok';
      title: string;
      rows: UsageRow[];
      context: UsageContextView;
      windows: UsageWindowView[];
    };

function readSessionUsage(sessionId: string): Promise<SessionTokenUsage> {
  const id = encodeURIComponent(sessionId);
  return authFetch<SessionTokenUsage>(`/sessions/${id}/token-usage`);
}

const cache = new Map<string, { resource: Resource<SessionTokenUsage>; refs: number; off: () => void }>();

const MOVING_STATUSES = new Set(['working', 'working_subagent']);

interface ListingSource {
  rows?(name: string): { activity_status?: string | null; session?: { id?: string } }[] | null;
  onChange?(fn: (names: string[]) => void): () => void;
}

function pushedStatus(sessionId: string): string | null | undefined {
  const push = (globalThis as { ListingPush?: ListingSource }).ListingPush;
  const rows = push && typeof push.rows === 'function' ? push.rows('list') : null;
  if (!rows) return undefined;
  const row = rows.find((r) => r?.session?.id === sessionId);
  return row ? row.activity_status ?? null : null;
}

function followStatus(sessionId: string, usage: Resource<SessionTokenUsage>): () => void {
  const push = (globalThis as { ListingPush?: ListingSource }).ListingPush;
  if (!push || typeof push.onChange !== 'function') return () => {};
  let last = pushedStatus(sessionId);
  return push.onChange((names) => {
    if (!names.includes('list') && !names.includes('$live')) return;
    const now = pushedStatus(sessionId);
    if (now === last) return;
    last = now;
    void usage.refresh();
  });
}

export function sessionUsage(sessionId: string): Resource<SessionTokenUsage> {
  let entry = cache.get(sessionId);
  if (!entry) {
    entry = {
      resource: resource<SessionTokenUsage>(() => readSessionUsage(sessionId), {
        intervalMs: SESSION_USAGE_POLL_MS,
        name: `session-usage:${sessionId}`,
        pollWhile: () => {
          const status = pushedStatus(sessionId);
          return status === undefined || status === null || MOVING_STATUSES.has(status);
        },
      }),
      refs: 0,
      off: () => {},
    };
    entry.off = followStatus(sessionId, entry.resource);
    cache.set(sessionId, entry);
  }
  entry.refs += 1;
  return entry.resource;
}

export function releaseSessionUsage(sessionId: string): void {
  const entry = cache.get(sessionId);
  if (!entry) return;
  entry.refs -= 1;
  if (entry.refs <= 0) {
    entry.off();
    entry.resource.stop();
    cache.delete(sessionId);
  }
}

function unavailableModel(title: string): UsagePanelModel {
  return { state: 'unchecked', title, message: t(USAGE_PANEL_KEYS.unchecked) };
}

function isUsagePanelModel(value: unknown): value is UsagePanelModel {
  if (!value || typeof value !== 'object') return false;
  const v = value as { state?: unknown; title?: unknown; rows?: unknown; windows?: unknown; context?: unknown };
  if (typeof v.title !== 'string') return false;
  if (v.state === 'absent' || v.state === 'unchecked') return true;
  if (v.state !== 'ok') return false;
  return Array.isArray(v.rows) && Array.isArray(v.windows) && typeof v.context === 'object' && v.context !== null;
}

export function sessionUsageLabels(
  usage: SessionTokenUsage | null,
  sessionName: string | null = null,
): UsagePanelModel {
  const result: unknown = usagePanelLabels(usage, t, { sessionName });
  if (isUsagePanelModel(result)) return result;
  console.warn('CloudeOpscenter: usagePanelLabels returned an unexpected shape', result);
  const title = sessionName && sessionName.trim() !== '' ? sessionName : t(USAGE_PANEL_KEYS.title);
  return unavailableModel(title);
}

export { scaleStep, scaleStepFor, SCALE_STOPS, WINDOW_SCALE_STOPS };
