import type { SessionInfo } from '../../opscenter/api/types';
import { t } from '../i18n/index.svelte';
import { hostOffline, usageLimitLabel } from '../led';
import { hostWindow } from './env';

export interface AgentMarkFacts {
  /* could not be determined */
  family: string | null;
  status: string | null;
  unread: boolean;
  startupGate: string | null;
  statusSource: string | null;
  activityHint: string | null;
  usageLimit?: string | null;
  parkedSummary?: string | null;
  hostOffline?: string | null;
  icon?: string | null;
  transport: string | null;
}

export const NOT_MEASURED: Readonly<AgentMarkFacts> = Object.freeze({
  family: null,
  status: null,
  unread: false,
  startupGate: null,
  statusSource: null,
  activityHint: null,
  usageLimit: null,
  parkedSummary: null,
  hostOffline: null,
  transport: null,
});

export interface ProviderMark {
  key: string;
  svg: string;
  label: string;
}

interface LegacyMarks {
  AgentFamilyIcon?: {
    svg(family: string | null, size?: number): string;
    normalize(family: string | null): string;
    labelFor(family: string | null): string;
  };
  SessionTransport?: { stateFor(name: string): string | undefined };
  WrapperMark?: {
    svg(wrapper: { icon: string | null; family: string | null }, size?: number): string;
    source(wrapper: { icon: string | null; family: string | null }): 'icon' | 'family';
  };
}

const legacy = (): LegacyMarks => (hostWindow() ?? {}) as unknown as LegacyMarks;

export function transportFor(tmuxName: string | null): string | null {
  const mod = legacy().SessionTransport;
  if (!tmuxName || !mod || typeof mod.stateFor !== 'function') return null;
  return mod.stateFor(tmuxName) ?? null;
}

export interface FaceRow {
  agent_family?: string | null;
  agent_wrapper_icon?: string | null;
  activity_status?: string | null;
  status?: string | null;
  unread?: boolean | null;
  startup_gate?: string | null;
  status_source?: string | null;
  activity_hint?: string | null;
  parked_summary?: string | null;
  usage_limit?: unknown;
  host_key?: string | null;
  host_label?: string | null;
  host_state?: string | null;
  tmux_session?: string | null;
  name?: string | null;
}

export interface FaceOptions {
  lifecycle?: 'stopped' | 'asleep';
  transport?: string | null;
}

export function faceFacts(row: FaceRow, opts: FaceOptions = {}): AgentMarkFacts {
  const family = row.agent_family ?? null;
  if (opts.lifecycle) {
    return { ...NOT_MEASURED, family, status: opts.lifecycle, unread: opts.lifecycle === 'asleep' && row.unread === true, transport: opts.transport ?? null };
  }
  return {
    family,
    icon: row.agent_wrapper_icon ?? null,
    status: row.activity_status ?? row.status ?? null,
    unread: row.unread === true,
    startupGate: row.startup_gate ?? null,
    statusSource: row.status_source ?? null,
    activityHint: row.activity_hint ?? null,
    parkedSummary: row.parked_summary ?? null,
    usageLimit: usageLimitLabel(row),
    hostOffline: hostOffline(row),
    transport: opts.transport !== undefined ? opts.transport : transportFor(row.tmux_session ?? row.name ?? null),
  };
}

export function agentMarkFacts(row: SessionInfo): AgentMarkFacts {
  return faceFacts(row);
}

export function providerMark(family: string | null, size = 14): ProviderMark {
  const icon = legacy().AgentFamilyIcon;
  const key = icon ? icon.normalize(family) : 'unknown';
  const catalogKey = `session.agentfamily.${key}`;
  const text = t(catalogKey);
  const label = text && text !== catalogKey ? text : (icon ? icon.labelFor(key) : key);
  return { key, svg: icon ? icon.svg(family, size) : '', label };
}

export interface WrapperMarkView extends ProviderMark {
  source: 'icon' | 'family';
}

export function wrapperMark(icon: string | null, family: string | null, size = 14): WrapperMarkView {
  const base = providerMark(family, size);
  const mod = legacy().WrapperMark;
  if (!mod) return { ...base, source: 'family' };
  const facts = { icon: icon ?? null, family };
  return { ...base, svg: mod.svg(facts, size), source: mod.source(facts) };
}

export function showsStatusLight(family: string | null | undefined): boolean {
  return family !== 'shell' && family !== 'browser';
}

export function sessionMark(family: string | null, icon: string | null | undefined, size = 14): ProviderMark {
  const base = providerMark(family, size);
  return family === 'custom' && icon ? { ...base, svg: wrapperMark(icon, family, size).svg } : base;
}

export const LAUNCH_MARK_PX = 24;
export const LAUNCH_MARK_PX_COMPACT = 20;
