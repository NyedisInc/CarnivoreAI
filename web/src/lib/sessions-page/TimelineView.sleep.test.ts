/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import TimelineView from './TimelineView.svelte';
import { SessionsData } from './sessions-data.svelte';
import { TimelineLanes } from './timeline-lanes.svelte';
import { session } from '../projects-shared/test-fixtures';
import { setLocale } from '../i18n/index.svelte';
import type { PageRow } from './filters';
import type { SessionTimeline } from '../../opscenter/cells/timeline/types';

setLocale('en');
(globalThis as { VisibilityObserver?: unknown }).VisibilityObserver = class {
    constructor(private readonly cb: (e: { isIntersecting: boolean }[]) => void) {}
    observe(): void { setTimeout(() => this.cb([{ isIntersecting: true }]), 0); }
    disconnect(): void {}
};
(globalThis as { ResizeObserver?: unknown }).ResizeObserver = class { observe(): void {} unobserve(): void {} disconnect(): void {} };

const NOW = Date.UTC(2026, 9, 14, 12, 0, 0);
const iso = (minBefore: number): string => new Date(NOW - minBefore * 60000).toISOString();

const row: PageRow = {
    s: session({ session_uuid: 'a1', title: 'sleeper', label: 'sleeper', state: 'asleep', row_id: 7, last_activity_at: iso(120), last_work_at: iso(120), last_seen_running_at: iso(120) }),
    groupKey: '1',
    projectRef: null,
    project: 'alpha',
    company: null,
    computer: null,
    provider: 'claude',
};

const TL = {
    session_uuid: 'a1',
    session_row_id: 7,
    family: 'claude',
    current_conversation: null,
    now: iso(0),
    bars: [{ conversation_id: 'c', current: false, level: null, began: null, started_at: iso(600), ended_at: iso(120), activity: [{ state: 'busy', start: iso(600), end: iso(120) }] }],
    marks: [],
    gaps: [{ id: 'g', conversation_id: 'c', start: iso(120), end: iso(30), open: false }],
} as unknown as SessionTimeline;

let handle: ReturnType<typeof mount> | null = null;
afterEach(() => {
    if (handle) void unmount(handle);
    handle = null;
    document.body.innerHTML = '';
});

test('a sleep gap draws the moon at the gap start and no dashed stretch', async () => {
    const data = new SessionsData({} as never, { records: () => Promise.resolve([]), counts: () => Promise.resolve({}) } as never, 'none', 'none');
    const lanes = new TimelineLanes({ timeline: () => Promise.resolve(TL) }, { onChange: () => () => {}, isLive: () => true });
    handle = mount(TimelineView, { target: document.body, props: { rows: [row], data, t: (k: string) => k, now: () => NOW, onPreview: () => {}, lanes } });
    flushSync();
    await vi.waitFor(() => expect(document.querySelector('.sp-tl-track .sp-tl-moon')).not.toBeNull());
    const moon = document.querySelector<HTMLElement>('.sp-tl-track .sp-tl-moon');
    expect(moon, 'moon').not.toBeNull();
    expect(moon!.style.left).toBe(`${((1440 - 120) / 1440 * 100).toFixed(3)}%`);
    expect(moon!.querySelector('[data-inner="asleep"]')).not.toBeNull();
    expect(document.querySelector('.sp-tl-sl')).toBeNull();
});
