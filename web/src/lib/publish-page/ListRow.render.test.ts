/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import ListRow from './ListRow.svelte';
import type { RowData } from './list-model';

const i18n = createI18n({ locale: 'en' }) as { t(key: string, params?: Record<string, unknown> | null): string };
const t = (key: string, params?: Record<string, unknown> | null): string => i18n.t(key, params);
const LONG = 'an-extremely-long-skill-name-for-line-wrap-testing-of-rows';

let app: Record<string, unknown> | null = null;
afterEach(() => {
    if (app) unmount(app as never);
    app = null;
    document.body.innerHTML = '';
});

const data = (over: Partial<RowData> = {}): RowData => ({
    key: 'k', location: 'skill:x', subId: null, kind: 'skill', name: LONG, version: '1.0.0', harness: 'claude', stage: null, wordKey: 'publish.page.row.word_unsent', date: null, wait: false, ...over,
});

function draw(row: RowData): HTMLElement {
    const target = document.createElement('ul');
    document.body.appendChild(target);
    app = mount(ListRow, { target, props: { row, selected: false, changed: false, submissions: false, t, onPick: vi.fn(), menu: () => null, onFlashEnd: vi.fn() } as never }) as never;
    flushSync();
    return target;
}

describe('the list row name', () => {
    it('draws a 58 character name in its own span, the aside outside it', () => {
        expect(LONG.length).toBe(58);
        const target = draw(data());
        const name = target.querySelector('.d-row__nm');
        expect(name?.textContent).toBe(LONG);
        expect(target.querySelector('.d-row__h')?.parentElement?.className).toBe('d-row__n');
        expect(name?.querySelector('.d-row__h')).toBeNull();
        expect(target.querySelector('button')?.getAttribute('aria-label')).toContain(`${LONG} (claude)`);
    });

    it('list.css keeps the name on one line with an ellipsis and never breaks inside it', () => {
        const css = readFileSync(resolve(process.cwd(), 'src/lib/publish-page/list.css'), 'utf8');
        const rule = /\.d-row__nm\s*\{([^}]*)\}/.exec(css)?.[1] ?? '';
        expect(rule).toContain('white-space: nowrap');
        expect(rule).toContain('overflow: hidden');
        expect(rule).toContain('text-overflow: ellipsis');
        expect(rule).not.toMatch(/break-word|anywhere/);
    });
});
