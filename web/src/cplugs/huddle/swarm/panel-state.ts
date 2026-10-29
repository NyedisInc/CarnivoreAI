import type { ListingRow } from '../../sdk';
import { STATUS_STATES, type Tell } from './characters/states';
import type { HuddleDensity } from '../huddle-density';

export const ACTIVITY_MS = 8000;

export type PanelDensity = 'condensed' | 'expanded' | 'detailed';

export const ACTIVITIES = ['talking', 'escalating', 'learning', 'promoted', 'done'] as const;

export const ALERT_RUNGS = ['routine', 'priority', 'immediate', 'flash'] as const;
export type AlertRung = (typeof ALERT_RUNGS)[number];

export interface PanelAgent {
  id: number;
  display_name: string;
  rank: string;
  state: string;
  thread_key: string;
  harness?: string | null;
  session_id?: string | null;
  session_row_id?: number | null;
  session_uuid?: string | null;
  tmux_session?: string | null;
  project_id?: number | null;
  company_id?: number | null;
  parent_id?: number | null;
  character_seed?: number | null;
  color_slot?: number | null;
  color_chosen?: boolean | null;
  shape?: string | null;
  tile_bg?: number | null;
  host_key?: string | null;
  host_label?: string | null;
  alert?: string | null;
  question_waiting?: boolean | null;
  alert_reason?: string | null;
  activity?: string | null;
  activity_at?: number | null;
  talking_with?: number | null;
  job?: string | null;
  effort?: string | null;
}

export interface DensityParts {
  name: boolean;
  provider: boolean;
  context: boolean;
  workingOn: boolean;
  list: boolean;
}

const PARTS: Record<PanelDensity, DensityParts> = {
  condensed: { name: false, provider: false, context: false, workingOn: false, list: false },
  expanded: { name: true, provider: false, context: false, workingOn: false, list: false },
  detailed: { name: true, provider: true, context: true, workingOn: true, list: true },
};

export function panelDensity(density: HuddleDensity): PanelDensity {
  return density === 'compact' ? 'condensed' : density === 'full' ? 'detailed' : 'expanded';
}

export function partsOf(density: PanelDensity): DensityParts {
  return PARTS[density];
}

export function columnsOf(section: 'companies' | 'projects' | 'agents', density: PanelDensity): number {
  if (section === 'companies') return 3;
  if (section === 'projects') return density === 'condensed' ? 5 : 4;
  return density === 'condensed' ? 8 : 6;
}

export function sizeOf(rank: string, density: PanelDensity, drawer = false): number {
  const rows = density === 'detailed';
  if (rank === 'alpha') return rows ? 64 : 96;
  if (rank === 'company') return rows ? 40 : 64;
  if (rank === 'project') return 40;
  return drawer && !rows ? 22 : 28;
}

export function alertOf(agent: PanelAgent): AlertRung | null {
  return (ALERT_RUNGS as readonly string[]).includes(agent.alert ?? '') ? (agent.alert as AlertRung) : null;
}

export function activityFresh(agent: PanelAgent, nowMs: number): boolean {
  return !!agent.activity && typeof agent.activity_at === 'number' && nowMs < agent.activity_at * 1000 + ACTIVITY_MS;
}

export function squareState(agent: PanelAgent, row: ListingRow | undefined, nowMs: number, rollup: string | null = null): string {
  const rung = alertOf(agent);
  if (rung) return `alert_${rung}`;
  if (activityFresh(agent, nowMs) && (ACTIVITIES as readonly string[]).includes(agent.activity ?? '')) return agent.activity as string;
  if (rollup) return rollup;
  if (agent.question_waiting === true) return 'question_waiting';
  if (agent.state === 'asleep') return 'asleep';
  if (row?.startup_gate === 'awaiting_startup_prompt') return 'startup_gate';
  if ((STATUS_STATES as readonly string[]).includes(row?.activity_status ?? '')) return row?.activity_status as string;
  return 'unknown';
}

export function sendOf(agent: PanelAgent, row: ListingRow | undefined): Tell | null {
  const status = row?.activity_status;
  if (status === 'question') return 'question';
  if (agent.question_waiting === true) return 'question_waiting';
  if (status === 'notice') return 'notice';
  return status === 'finished_unread' ? 'unread' : null;
}

export function colorOf(agent: PanelAgent): number {
  const slot = agent.color_slot;
  if (typeof slot === 'number' && slot >= 1 && slot <= 8) return Math.round(slot);
  return (Math.abs(agent.character_seed ?? agent.id) % 8) + 1;
}

export function seedOf(agent: PanelAgent): number {
  return agent.character_seed ?? agent.id;
}

export function subSeeds(agent: PanelAgent, agents: readonly PanelAgent[]): number[] {
  return agents.filter((a) => a.parent_id === agent.id && a.state !== 'asleep').slice(0, 3).map(seedOf);
}

export function talkingSide(agent: PanelAgent, agents: readonly PanelAgent[], nowMs: number): 'l' | 'r' {
  if (!activityFresh(agent, nowMs) || agent.activity !== 'talking' || agent.talking_with == null) return 'l';
  const partner = agents.find((a) => a.id === agent.talking_with);
  if (!partner || !activityFresh(partner, nowMs) || partner.activity !== 'talking') return 'l';
  return agent.id < partner.id ? 'l' : 'r';
}

export function priorityCount(agents: readonly PanelAgent[]): number {
  return agents.filter((a) => {
    const rung = alertOf(a);
    return rung !== null && ALERT_RUNGS.indexOf(rung) >= ALERT_RUNGS.indexOf('priority');
  }).length;
}

export function contextScale(pct: number): number {
  return pct >= 95 ? 5 : pct >= 85 ? 4 : pct >= 75 ? 3 : pct >= 60 ? 2 : 1;
}
