import type { Automation, SessionChoice } from './api';

function labelOf(record: SessionChoice): string {
  const resolver = (globalThis as { SessionLabel?: { resolve(row: { label: string | null; name: string | null }): string | null } }).SessionLabel;
  const row = { label: record.title ?? null, name: record.tmux_name ?? null };
  const resolved = resolver ? resolver.resolve(row) : (row.label ?? '').trim() || row.name;
  return (resolved ?? '').trim();
}

/* label: ' */
export function sessionChoices(records: readonly SessionChoice[], automations: readonly Automation[]): SessionChoice[] {
  const targeted = new Set(automations.map((a) => (a.target.kind === 'session_message' ? String(a.target.session_uuid ?? '') : '')));
  const live = (r: SessionChoice): boolean => r.lifecycle === 'running' || r.asleep === true;
  const named = new Set<string>();
  const out: SessionChoice[] = [];
  const ordered = [...records].sort((a, b) => Number(b.lifecycle === 'running') - Number(a.lifecycle === 'running'));
  for (const r of ordered) {
    const mine = targeted.has(r.session_uuid ?? '');
    if (!live(r) && !mine) continue;
    if (!mine && r.tmux_name) {
      if (named.has(r.tmux_name)) continue;
      named.add(r.tmux_name);
    }
    out.push({ ...r, label: labelOf(r) || undefined });
  }
  return out;
}
