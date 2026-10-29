/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import TimelineView from './TimelineView.svelte';
import { SessionsData } from './sessions-data.svelte';
import { TimelineLanes } from './timeline-lanes.svelte';
import { session } from '../projects-shared/test-fixtures';
import { setLocale } from '../i18n/index.svelte';
import type { PageRow } from './filters';

setLocale('en');
(globalThis as { VisibilityObserver?: unknown }).VisibilityObserver = class {
    constructor(private readonly cb: (e: { isIntersecting: boolean }[]) => void) {}
    observe(): void { setTimeout(() => this.cb([{ isIntersecting: true }]), 0); }
    disconnect(): void {}
};
(globalThis as { ResizeObserver?: unknown }).ResizeObserver = class { observe(): void {} unobserve(): void {} disconnect(): void {} };

const NOW = Date.UTC(2026, 9, 14, 12, 0, 0);
const remote: PageRow = {
    s: session({ session_uuid: 'r1', title: 'peer', label: 'peer', state: 'running', row_id: 7, last_activity_at: new Date(NOW - 60000).toISOString() }),
    groupKey: '1',
    projectRef: null,
    project: 'alpha',
    company: null,
    computer: 'mac mini',
    provider: 'claude',
};

let handle: ReturnType<typeof mount> | null = null;
afterEach(() => {
    if (handle) void unmount(handle);
    handle = null;
    document.body.innerHTML = '';
});

test('a paired computer lane never asks for a timeline by its foreign row id', async () => {
    const timeline = vi.fn(() => Promise.reject(new Error('must not be asked')));
    const data = new SessionsData({} as never, { records: () => Promise.resolve([]), counts: () => Promise.resolve({}) } as never, 'none', 'none');
    const lanes = new TimelineLanes({ timeline }, { onChange: () => () => {}, isLive: () => true });
    handle = mount(TimelineView, { target: document.body, props: { rows: [remote], data, t: (k: string) => k, now: () => NOW, onPreview: () => {}, lanes } });
    flushSync();
    await new Promise((r) => setTimeout(r, 30));
    expect(document.querySelector('.sp-tl-lane')).not.toBeNull();
    expect(timeline).not.toHaveBeenCalled();
});
