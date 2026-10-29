import { escAttr } from '../drawer/row-controls';
import { t } from '../i18n/index.svelte';

export function runningOf(row: { subagents_running?: unknown } | null | undefined): number | null {
    const n = row ? row.subagents_running : null;
    return typeof n === 'number' && Number.isFinite(n) && n > 0 ? Math.floor(n) : null;
}

export function rollupHtml(rows: ReadonlyArray<{ session_id?: string; name?: string; subagents_running?: unknown }>): string {
    const seen = new Set<string | undefined>();
    let sum = 0;
    for (const r of Array.isArray(rows) ? rows : []) {
        const running = runningOf(r);
        const id = r && (r.session_id || r.name);
        if (running === null || seen.has(id)) continue;
        seen.add(id);
        sum += running;
    }
    if (sum === 0) return '';
    return `<span class="subagent-count subagent-count--rollup">${escAttr(t('subagents.badge', { count: sum }))}</span>`;
}
