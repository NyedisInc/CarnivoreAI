/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import { readFileSync } from 'node:fs';
import PivotView from './PivotView.svelte';
import { SessionsData } from './sessions-data.svelte';
import { session } from '../projects-shared/test-fixtures';
import { setLocale } from '../i18n/index.svelte';
import type { PageRow } from './filters';

setLocale('en');
(globalThis as { VisibilityObserver?: unknown }).VisibilityObserver = class { observe(): void {} disconnect(): void {} };
(globalThis as { ResizeObserver?: unknown }).ResizeObserver = class { observe(): void {} unobserve(): void {} disconnect(): void {} };
vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener: () => {}, removeEventListener: () => {} }));

const NOW = Date.UTC(2026, 9, 14, 12, 0, 0);
let handle: ReturnType<typeof mount> | null = null;
afterEach(() => { if (handle) void unmount(handle); handle = null; document.body.innerHTML = ''; });

const css = (f: string): string => readFileSync(new URL(f, import.meta.url), 'utf8');

test('a chip with a long summary keeps name and line in the label column, cut or not', () => {
    const data = new SessionsData({} as never, { records: () => Promise.resolve([]), counts: () => Promise.resolve({}) } as never, 'none', 'none');
    const row: PageRow = {
        s: session({ session_uuid: 'a', title: 'a', label: 'a', state: 'asleep', row_id: 1, last_activity_at: new Date(NOW - 60000).toISOString() }),
        groupKey: 'x', projectRef: null, project: 'p', company: null, computer: null, provider: 'claude',
    };
    handle = mount(PivotView, { target: document.body, props: { rows: [row], data, t: (k: string) => k, now: () => NOW, onPreview: () => {}, onAct: () => {} } });
    flushSync();
    const btn = document.querySelector<HTMLElement>('.sp-pv-chip [data-cb]');
    expect(btn).not.toBeNull();
    const span = document.createElement('span');
    span.setAttribute('data-btn-label', '');
    span.append(...Array.from(btn!.childNodes));
    btn!.append(span);
    const line = btn!.querySelector('.sp-pv-line');
    expect(line).not.toBeNull();
    expect(span.contains(line)).toBe(true);
    expect(css('./pivot.css')).toMatch(/\.sp-pv \[data-cb\] \{[^}]*grid-template-columns: 12px minmax\(0, 1fr\)/);
    expect(css('./pivot.css')).toMatch(/\.sp-pv-line \{[^}]*grid-column: 2/);
    expect(css('../base/elements.css')).toMatch(/:where\(\[data-btn='row'\] > \[data-btn-label\]\) \{\s*display: contents;/);
});
