import { elapsedSeconds } from '../../api';
import type { SessionTokenUsage, UsageContextView, UsagePanelModel, UsageRow, UsageWindowView } from '../../api';
import { t } from '../../../lib/i18n/index.svelte';
import { clockText } from '../../lib/clock';
import { elapsed } from '../../lib/format';
import type { AgentCostGroup, ArgentCostView } from '../../../lib/argent-cost/cost-view';

const DAY_MS = 86_400_000;

export type StatsCell =
  | { kind: 'context'; key: 'context'; label: string; view: UsageContextView }
  | { kind: 'window'; key: string; label: string; view: UsageWindowView; resetAt: string | null }
  | { kind: 'model'; key: 'model'; label: string; row: UsageRow; effort: string | null }
  | { kind: 'text'; key: string; label: string; row: UsageRow }
  | { kind: 'argent'; key: 'argent'; label: string; view: ArgentCostView }
  | { kind: 'gateway_agent'; key: string; label: string; costText: string; agentId: string | null };

export function resetClock(resetsAt: string | null | undefined, nowMs: number): string | null {
  const at = resetsAt ? Date.parse(resetsAt) : NaN;
  if (!Number.isFinite(at) || at <= nowMs || at - nowMs >= DAY_MS) return null;
  return t('usage.window.reset_at', { time: clockText(at) });
}

function ageCell(createdAt: string | null, nowMs: number): StatsCell[] {
  const seconds = elapsedSeconds(createdAt, nowMs);
  if (seconds === null) return [];
  const label = t('usage.foot.age');
  return [{ kind: 'text', key: 'age', label, row: { key: 'age', label, text: elapsed(seconds) } }];
}

export function statsGroups(
  model: UsagePanelModel,
  payload: SessionTokenUsage | null,
  nowMs: number,
  createdAt: string | null = null,
  argent: ArgentCostView | null = null,
  argentAgents: AgentCostGroup[] | null = null,
): StatsCell[][] {
  if (model.state !== 'ok') return [];
  const rows: Record<string, UsageRow> = Object.fromEntries(model.rows.map((r) => [r.key, r]));
  const text = (key: string): StatsCell[] => (rows[key] ? [{ kind: 'text', key, label: rows[key].label, row: rows[key] }] : []);

  const first: StatsCell[] = [{ kind: 'context', key: 'context', label: model.context.title, view: model.context }];
  const modelRow = rows.model;
  if (modelRow?.spans?.[0]?.text) {
    const hasEffort = typeof payload?.effort === 'string' && payload.effort.trim() !== '' && modelRow.spans.length > 2;
    first.push({ kind: 'model', key: 'model', label: modelRow.label, row: modelRow,
      effort: hasEffort ? (modelRow.spans[2]?.text ?? null) : null });
  }
  first.push(...text('tokens'), ...text('cache'));

  const raw = payload?.account?.windows ?? [];
  const windows: StatsCell[] = model.windows.map((view) => ({
    kind: 'window', key: view.key, label: view.label, view,
    resetAt: resetClock(raw.find((w) => `window:${w.kind}` === view.key)?.resets_at, nowMs),
  }));

  const argentCell: StatsCell[] = argent ? [{ kind: 'argent', key: 'argent', label: t('argent.cost.foot_label'), view: argent }] : [];
  const agentCells: StatsCell[] = (argent ? argentAgents ?? [] : []).flatMap((g) => [
    { kind: 'gateway_agent' as const, key: `argent-item:${g.itemId}`, label: g.itemName || t('argent.card.agent_item_none'), costText: g.totalText, agentId: null },
    ...g.agents.map((a) => ({ kind: 'gateway_agent' as const, key: `gateway-agent:${g.itemId}:${a.agentId}`, label: a.name ?? t('argent.card.agent_root'), costText: a.costText, agentId: a.agentId })),
  ]);
  const spend: StatsCell[] = [...text('cost'), ...argentCell, ...agentCells, ...ageCell(createdAt, nowMs)];
  const who: StatsCell[] = payload?.account ? text('account') : [];
  who.push(...text('login'), ...text('limits'));

  return [first, windows, spend, who].filter((group) => group.length > 0);
}
