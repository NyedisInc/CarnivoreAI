import { t } from '../i18n/index.svelte';
import type { BodyFlag } from './row-body';

const FAILING = new Set(['blocked', 'host_failed']);

export function shortVersion(version: string): string {
    const m = /^(\d+\.\d+)/.exec(version);
    return m?.[1] ?? version;
}

export function codexHelpersFlag(r: Record<string, unknown>): BodyFlag | null {
    if (r.agent_family !== 'codex') return null;
    const mark = r.codex_helpers as { verdict?: unknown; version?: unknown } | null | undefined;
    if (!mark || typeof mark.verdict !== 'string' || !FAILING.has(mark.verdict)) return null;
    const version = typeof mark.version === 'string' && mark.version ? shortVersion(mark.version) : 'codex';
    return { kind: 'codex_helpers', tone: 'bad', text: t(`codex_helpers.row.${mark.verdict}`, { version }) };
}
