import { formatMicros } from './money';

interface CostBudget {
  state?: string; spent_micros?: number | null; cap_micros?: number | null; effective_spent_micros?: number | null;
  owner_name?: string; viewer_is_owner?: boolean | null; governing_item_id?: string; governing_item_title?: string;
}
export interface CostAgent { agent_id: string; name?: string | null; item_id?: string; cost_micros?: number | null }
interface CostSession { items?: string[]; cost?: { cost_micros?: number | null } | null; agents?: CostAgent[] | null }
export interface ArgentCostSnapshot {
  enabled?: boolean;
  state?: string;
  as_of?: string | null;
  sessions?: Record<string, CostSession>;
  items?: Record<string, { name?: string | null; held?: boolean; cost?: { cost_micros?: number | null } | null; budget?: CostBudget | null }>;
}

export interface ArgentCostView {
  costText: string;
  measured: boolean;
  pct: number | null;
  pctText: string;
  scale: number | null;
}

export function budgetScale(pct: number): number {
  return pct >= 100 ? 5 : pct >= 90 ? 4 : pct >= 80 ? 3 : pct >= 50 ? 2 : 1;
}

function itemPct(b: CostBudget | null | undefined): number | null {
  if (!b) return null;
  const spent = b.effective_spent_micros ?? b.spent_micros;
  if (b.state === 'paused') return 100;
  if (typeof spent === 'number' && typeof b.cap_micros === 'number' && b.cap_micros > 0) return Math.floor((spent / b.cap_micros) * 100);
  return null;
}

export function argentCostView(snap: ArgentCostSnapshot | null | undefined, rowId: number | null | undefined): ArgentCostView | null {
  if (!snap || snap.enabled !== true || snap.state !== 'ok' || rowId === null || rowId === undefined) return null;
  const row = snap.sessions?.[String(rowId)];
  if (!row) return null;
  const micros = row.cost?.cost_micros;
  const measured = typeof micros === 'number' && Number.isFinite(micros);
  let pct: number | null = null;
  for (const id of row.items ?? []) {
    const here = itemPct(snap.items?.[id]?.budget);
    if (here !== null && (pct === null || here > pct)) pct = here;
  }
  return {
    costText: formatMicros(measured ? micros : null),
    measured,
    pct,
    pctText: pct === null ? '-' : `${pct}%`,
    scale: pct === null ? null : budgetScale(pct),
  };
}

export interface CardCostItem { id: string; name: string; costText: string; pctText: string; scale: number | null; held: boolean; lift: LiftView }
export interface LiftView { isOwner: boolean; owner: string; governingId: string; governingTitle: string; capMicros?: number | null; spentMicros?: number | null }
export interface CardCostShare { rowId: number; costText: string }
export interface CardCostView extends ArgentCostView { held: boolean; items: CardCostItem[]; split: CardCostShare[] }

export function cardCostView(snap: ArgentCostSnapshot | null | undefined, rowId: number | null | undefined): CardCostView | null {
  const base = argentCostView(snap, rowId);
  const row = base && snap ? snap.sessions?.[String(rowId)] : undefined;
  if (!base || !snap || !row || (row.items ?? []).length === 0) return null;
  const ids = row.items ?? [];
  const items = ids.map((id): CardCostItem => {
    const it = snap.items?.[id];
    const micros = it?.cost?.cost_micros;
    const pct = itemPct(it?.budget);
    return {
      id,
      name: it?.name || id,
      costText: formatMicros(typeof micros === 'number' && Number.isFinite(micros) ? micros : null),
      pctText: pct === null ? '-' : `${pct}%`,
      scale: pct === null ? null : budgetScale(pct),
      held: it?.held === true,
      lift: {
        isOwner: it?.budget?.viewer_is_owner === true,
        owner: it?.budget?.owner_name ?? '',
        governingId: it?.budget?.governing_item_id ?? '',
        governingTitle: it?.budget?.governing_item_title ?? '',
        capMicros: it?.budget?.cap_micros ?? null,
        spentMicros: it?.budget?.effective_spent_micros ?? it?.budget?.spent_micros ?? null,
      },
    };
  });
  const split: CardCostShare[] = [];
  for (const [key, other] of Object.entries(snap.sessions ?? {})) {
    if (!(other.items ?? []).some((id) => ids.includes(id))) continue;
    const m = other.cost?.cost_micros;
    const share = { rowId: Number(key), costText: formatMicros(typeof m === 'number' && Number.isFinite(m) ? m : null) };
    if (key === String(rowId)) split.unshift(share);
    else split.push(share);
  }
  return { ...base, held: items.some((i) => i.held), items, split };
}

export function heldRowIds(snap: ArgentCostSnapshot | null | undefined): Set<number> {
  const out = new Set<number>();
  if (!snap || snap.enabled !== true || snap.state !== 'ok') return out;
  for (const [key, row] of Object.entries(snap.sessions ?? {})) {
    if ((row.items ?? []).some((id) => snap.items?.[id]?.held === true)) out.add(Number(key));
  }
  return out;
}

export interface AgentCostRow { agentId: string; name: string | null; costText: string }
export interface AgentCostGroup { itemId: string; itemName: string; totalText: string; agents: AgentCostRow[] }

export function agentSplitView(snap: ArgentCostSnapshot | null | undefined, rowId: number | null | undefined): AgentCostGroup[] | null {
  if (!snap || snap.enabled !== true || snap.state !== 'ok' || rowId === null || rowId === undefined) return null;
  const agents = snap.sessions?.[String(rowId)]?.agents;
  if (!agents || agents.length === 0) return null;
  const groups = new Map<string, { agents: AgentCostRow[]; total: number; measured: boolean }>();
  for (const a of agents) {
    const id = a.item_id ?? '';
    const g = groups.get(id) ?? { agents: [], total: 0, measured: true };
    const ok = typeof a.cost_micros === 'number' && Number.isFinite(a.cost_micros);
    if (ok) g.total += a.cost_micros as number;
    else g.measured = false;
    g.agents.push({ agentId: a.agent_id, name: a.name ?? null, costText: formatMicros(ok ? (a.cost_micros as number) : null) });
    groups.set(id, g);
  }
  return [...groups].map(([id, g]) => ({ itemId: id, itemName: snap.items?.[id]?.name || id, totalText: formatMicros(g.measured ? g.total : null), agents: g.agents }));
}
