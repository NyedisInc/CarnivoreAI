import { isAgentKind } from '../drawer/bucketing';
import type { PackMachine } from '../pack-machines/pack-machines-store.svelte';
import type { SidebarRow } from './legacy';

export type KeyedMachine = PackMachine & { host_key?: string | null };

interface LightGlobals {
    StatusLed?: { ledHtml(o: { inner: string; outer: string }): string };
    SessionStatusSummary?: { summaryHtml(rows: unknown[]): string };
}

export function agentsOf(m: Pick<KeyedMachine, 'is_self' | 'state' | 'host_key'>, rows: readonly SidebarRow[]): SidebarRow[] | null {
    const agents = rows.filter((r) => isAgentKind(r as never));
    if (m.is_self) return agents.filter((r) => !r.host_key || r.host_key === 'local');
    if (!m.host_key || m.state !== 'connected') return null;
    const theirs = agents.filter((r) => r.host_key === m.host_key);
    return theirs.some((r) => typeof r.host_state === 'string' && r.host_state !== 'up') ? null : theirs;
}

export function hostLightHtml(m: KeyedMachine, rows: readonly SidebarRow[], host: unknown = globalThis): string {
    const g = host as LightGlobals;
    if (!g.StatusLed || !g.SessionStatusSummary) return '';
    const agents = agentsOf(m, rows);
    const html = agents === null
        ? g.SessionStatusSummary.summaryHtml([])
        : agents.length === 0
            ? g.StatusLed.ledHtml({ inner: 'idle', outer: 'steady' })
            : g.SessionStatusSummary.summaryHtml(agents);
    return html.replace(/ title="[^"]*"/, '');
}
