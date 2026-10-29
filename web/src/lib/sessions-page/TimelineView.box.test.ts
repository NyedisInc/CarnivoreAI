/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import { readFileSync } from 'node:fs';
import TimelineView from './TimelineView.svelte';
import { SessionsData } from './sessions-data.svelte';
import { TimelineLanes } from './timeline-lanes.svelte';
import { session } from '../projects-shared/test-fixtures';
import { setLocale } from '../i18n/index.svelte';
import type { PageRow } from './filters';

vi.mock('../project-colors/store.svelte', () => ({ projectColorOf: (id: number | null) => (id === 1 ? 'red' : null) }));
setLocale('en');
(globalThis as { VisibilityObserver?: unknown }).VisibilityObserver = class { observe(): void {} disconnect(): void {} };
(globalThis as { ResizeObserver?: unknown }).ResizeObserver = class { observe(): void {} unobserve(): void {} disconnect(): void {} };

const NOW = Date.UTC(2026, 9, 14, 12, 0, 0);
const iso = (m: number): string => new Date(NOW - m * 60000).toISOString();
const mk = (label: string, id: number | null, name: string): PageRow => ({
    s: session({ session_uuid: label, title: label, label, state: 'running', row_id: 1, last_activity_at: iso(5) }),
    groupKey: String(id), projectRef: id === null ? null : ({ id, name } as PageRow['projectRef']), project: name, company: null, computer: null, provider: 'claude',
});
let handle: ReturnType<typeof mount> | null = null;
afterEach(() => { if (handle) void unmount(handle); handle = null; document.body.innerHTML = ''; });

test('open colored group: one box round head and lanes; folded: head alone; plain group unframed', () => {
    const data = new SessionsData({} as never, { records: () => Promise.resolve([]), counts: () => Promise.resolve({}) } as never, 'none', 'none');
    const lanes = new TimelineLanes({ timeline: () => new Promise(() => {}) }, { onChange: () => () => {}, isLive: () => true });
    const rows = [mk('a', 1, 'red proj'), mk('b', 1, 'red proj'), mk('c', 2, 'plain')];
    handle = mount(TimelineView, { target: document.body, props: { rows, data, t: (k: string) => k, now: () => NOW, onPreview: () => {}, lanes } });
    flushSync();
    const boxes = [...document.querySelectorAll<HTMLElement>('.sp-tl-gbox')];
    expect(boxes).toHaveLength(2);
    const [plain, red] = boxes as [HTMLElement, HTMLElement];
    expect(red.hasAttribute('data-block')).toBe(true);
    expect(red.querySelectorAll('.sp-tl-lane')).toHaveLength(2);
    expect(red.querySelector(':scope > [data-tl-grp]')).not.toBeNull();
    expect(red.querySelector<HTMLElement>('.sp-tl-lane')!.style.getPropertyValue('--tl-busy')).not.toBe('');
    expect(plain.hasAttribute('data-block')).toBe(false);
    red.querySelector<HTMLElement>('[data-tl-grp]')!.click();
    flushSync();
    expect(red.hasAttribute('data-block')).toBe(false);
    expect(red.querySelector('[data-tl-grp]')!.hasAttribute('data-block')).toBe(true);
    expect(red.querySelectorAll('.sp-tl-lane')).toHaveLength(0);
});

test('the finished line takes the project color like the working band', () => {
    const css = readFileSync('src/lib/sessions-page/timeline.css', 'utf8');
    expect(css).toMatch(/\.sp-tl-wt\[data-kind='done'\]\s*\{\s*background: var\(--tl-busy, var\(--led-color-unread\)\)/);
});
