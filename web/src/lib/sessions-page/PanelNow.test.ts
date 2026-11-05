/** @vitest-environment jsdom */
import { flushSync, mount, unmount } from 'svelte';
import { afterEach, expect, test } from 'vitest';
import PanelNow from './PanelNow.svelte';

const t = (key: string, vars?: Record<string, unknown>): string =>
    key === 'sessions.page.panel.now.model_val' ? `${vars?.model}, context ${vars?.pct}% used` : key;

const mounted: ReturnType<typeof mount>[] = [];
afterEach(() => { for (const c of mounted.splice(0)) void unmount(c); document.body.replaceChildren(); });

function modelLine(live: Record<string, unknown>): string | null {
    const target = document.createElement('div');
    document.body.append(target);
    const row = { s: { state: 'running' }, computer: null };
    mounted.push(mount(PanelNow, { target, props: { row, live, listingDown: false, t, now: 0 } as never }));
    flushSync();
    const dts = [...target.querySelectorAll('dt')];
    const at = dts.findIndex((d) => d.textContent === 'sessions.page.panel.now.model');
    return at < 0 ? null : (target.querySelectorAll('dd')[at]?.textContent ?? null);
}

test('the model is trimmed of its vendor prefix and the percent is the spoken, clamped one', () => {
    expect(modelLine({ running_model: 'claude-opus-5-5', running_context_used_pct: 41.6 })).toBe('opus-5-5, context 42% used');
    expect(modelLine({ running_model: 'claude-opus-5-5', running_context_used_pct: 140 })).toBe('opus-5-5, context 100% used');
});

test('an unmeasured percent prints the model alone, and no model prints no line', () => {
    expect(modelLine({ running_model: 'claude-opus-5-5', running_context_used_pct: null })).toBe('opus-5-5');
    expect(modelLine({ running_model: null })).toBeNull();
});
