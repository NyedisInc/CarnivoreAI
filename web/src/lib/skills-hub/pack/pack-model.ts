import type { PackSkills, PackRow, PlanCall } from './pack-skills-api';

export const CELL: Record<string, { slug: string; mark: string }> = {
  'in sync': { slug: 'in_sync', mark: '●' },
  syncing: { slug: 'syncing', mark: '◔' },
  missing: { slug: 'missing', mark: '-' },
  differs: { slug: 'differs', mark: '◐' },
  'only here': { slug: 'only_here', mark: '◆' },
  same: { slug: 'same', mark: '=' },
  'missing on alpha': { slug: 'missing_on_alpha', mark: '!' },
  conflict: { slug: 'conflict', mark: '✕' },
  offline: { slug: 'offline', mark: '○' },
  'older carnivore': { slug: 'older', mark: '○' },
  'alpha is one way here': { slug: 'one_way', mark: '○' },
  'alpha differs': { slug: 'alpha_differs', mark: '○' },
};

export interface PackColumn {
  id: string;
  label: string;
  alpha: boolean;
}

export function columns(view: PackSkills): PackColumn[] {
  if (view.role !== 'alpha') return [{ id: 'self', label: 'this computer', alpha: false }];
  const peers = Object.entries(view.peers ?? {}).map(([id, p]) => ({ id, label: p.label, alpha: false }));
  return [{ id: 'self', label: view.alpha.label || 'this computer', alpha: true }, ...peers];
}

export function cellWord(view: PackSkills, row: PackRow, column: PackColumn): string {
  if (view.role !== 'alpha') return row.state;
  if (row.state === 'held') return column.alpha ? 'missing on alpha' : (row.cells?.[column.id] ?? '');
  if (column.alpha) return row.state === 'only elsewhere' ? 'missing' : row.state === 'unsynced' ? 'only here' : 'in sync';
  return row.cells?.[column.id] ?? '';
}

export function conflictReason(view: PackSkills, row: PackRow, column: PackColumn): string {
  const mine = (view.peers?.[column.id]?.conflicts ?? []).find((c) => c[0] === row.family && c[1] === row.name);
  return mine?.[2] ?? row.reason ?? '';
}

export const REASON_CODES = [
  'not_loaded', 'not_in_catalog', 'untrusted_key', 'kind_changed', 'version_not_in_catalog', 'digest_differs', 'key_revoked',
  'version_revoked', 'signature_failed', 'review_not_clean', 'unreachable', 'busy', 'archive_refused', 'consent_mismatch',
  'fork_there', 'other_item_there', 'orphan_record_there', 'family_missing_here', 'scope_shadowed', 'root_missing', 'root_link',
  'name_taken', 'name_reserved', 'no_harness', 'bad_entry', 'keeps_changing', 'unknown', 'catalog_record',
  'catalog_record_incomplete', 'edited_on_alpha', 'other_name_on_alpha', 'from_warez_there',
] as const;

export function reasonLabel(raw: string, t: (key: string, params?: Record<string, unknown> | null) => string): string {
  for (const code of REASON_CODES) {
    for (const family of ['claude', 'codex']) {
      const text = t(`skills.pack.reason.${code}`, { family });
      if (text === raw) return text;
    }
  }
  return raw;
}

export interface SkillGroup {
  name: string;
  rows: PackRow[];
  syncable: PackRow[];
  held: PackRow[];
  on: boolean;
}

const FAMILY_ORDER = ['claude', 'codex'];

export function groupRows(rows: PackRow[]): SkillGroup[] {
  const by = new Map<string, PackRow[]>();
  for (const row of rows) by.set(row.name, [...(by.get(row.name) ?? []), row]);
  return [...by.entries()]
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    .map(([name, list]) => {
      const sorted = [...list].sort((a, b) => FAMILY_ORDER.indexOf(a.family) - FAMILY_ORDER.indexOf(b.family));
      const syncable = sorted.filter((r) => r.state !== 'held');
      return { name, rows: sorted, syncable, held: sorted.filter((r) => r.state === 'held'), on: syncable.length > 0 && syncable.every((r) => r.synced) };
    });
}

const WORST: Record<string, number> = {
  conflict: 9, 'missing on alpha': 8, offline: 7, 'older carnivore': 7, 'alpha is one way here': 7, 'alpha differs': 7,
  differs: 6, missing: 6, syncing: 4, 'in sync': 3, 'only here': 2, same: 2,
};

export function worstCell(view: PackSkills, group: SkillGroup, column: PackColumn): { word: string; row: PackRow } | null {
  let best: { word: string; row: PackRow } | null = null;
  for (const row of group.rows) {
    const word = cellWord(view, row, column);
    if (word && (!best || (WORST[word] ?? 1) > (WORST[best.word] ?? 1))) best = { word, row };
  }
  return best;
}

export function groupCall(group: SkillGroup, synced: boolean): PlanCall {
  const families = group.syncable.map((r) => r.family);
  return { kind: 'skill', family: families[0] ?? group.rows[0]!.family, families, name: group.name, synced, removeElsewhere: false };
}
