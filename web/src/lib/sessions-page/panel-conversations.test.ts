/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import PanelConversations from './PanelConversations.svelte';
import { timelineOf, type PanelConversations as Convs } from './panel-data.svelte';
import type { SessionTimeline } from '../../opscenter/cells/timeline/types';
import { setLocale } from '../i18n/index.svelte';

setLocale('en');

const conv = { conversation_id: 'C', current: true, started_at: '2026-10-14T08:00:00Z', ended_at: null, ended_reason: null, first_prompt: 'hi', summary: null, transcript_on_disk: true };
const LIST: Convs = { current: conv, previous: [] };
const bar = (busy: number) => ({ conversation_id: 'C', current: true, level: null, began: null, started_at: null, ended_at: null, busy_seconds: busy });
const mark = (id: string, kind: string, conversation_id = 'C') => ({ id, kind, conversation_id, at: '2026-10-14T09:00:00Z' });
const TIMELINE = { bars: [bar(3600), bar(1800)], marks: [mark('compact:1', 'compact'), mark('bookmark:1', 'bookmark'), mark('compact:2', 'compact', 'other')] } as unknown as SessionTimeline;

let app: ReturnType<typeof mount> | null = null;
afterEach(() => {
    if (app) unmount(app);
    app = null;
    document.body.innerHTML = '';
});

test('timelineOf sums the bars of one conversation and keeps only its compact marks', () => {
    const tl = timelineOf(TIMELINE, 'C');
    expect(tl.busySeconds).toBe(5400);
    expect(tl.compacts.map((k) => k.id)).toEqual(['compact:1']);
    expect(timelineOf(null, 'C').busySeconds).toBeNull();
});

test('the conversation row shows its summed busy time and one compact mark', () => {
    const t = (key: string, vars?: Record<string, unknown> | null) => (vars ? `${key} ${Object.values(vars).join(' ')}` : key);
    app = mount(PanelConversations, { target: document.body, props: { list: LIST, timeline: TIMELINE, codex: false, gone: false, status: 'ready', resuming: null, notice: null, t, onResume: () => {} } });
    flushSync();
    const li = document.querySelector('[data-conv="C"]')!;
    expect(li.querySelector('[data-busy]')?.getAttribute('data-busy')).toBe('5400');
    expect(li.querySelector('[data-busy]')?.textContent).toContain('1h 30m');
    expect(li.querySelectorAll('[data-mark="compact"]').length).toBe(1);
});
