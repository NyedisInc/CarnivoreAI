/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const seen: Record<string, unknown>[] = [];

vi.mock('../StatusLed.svelte', () => ({
    default: (_anchor: unknown, props: Record<string, unknown>) => {
        const keys = ['status', 'unread', 'startupGate', 'statusSource', 'activityHint', 'parkedSummary', 'transport', 'hostOffline', 'usageLimit', 'size', 'bare'];
        seen.push(Object.fromEntries(keys.filter((k) => k in props).map((k) => [k, props[k]])));
    },
}));

import SessionFace from './SessionFace.svelte';

let app: Record<string, unknown> | null = null;
afterEach(() => {
    if (app) unmount(app);
    app = null;
    seen.length = 0;
    document.body.innerHTML = '';
});

function face(props: Record<string, unknown>): HTMLElement {
    const target = document.createElement('div');
    document.body.append(target);
    app = mount(SessionFace as never, { target, props });
    flushSync();
    return target;
}

const ROW = {
    agent_family: 'claude', activity_status: 'question', unread: true, startup_gate: 'awaiting_startup_prompt', status_source: 'registry',
    activity_hint: 'shell', parked_summary: 'waiting on the build', usage_limit: { resets_at: null },
    host_key: 'peer-1', host_label: 'studio', host_state: 'disconnected', tmux_session: 'cc_a',
};

describe('SessionFace hands the light every signal', () => {
    test('every signal on the row reaches StatusLed, with the transport the caller knows', () => {
        face({ row: ROW, transport: 'disconnected', size: '9px', bare: true });
        expect(seen).toEqual([{
            status: 'question', unread: true, startupGate: 'awaiting_startup_prompt', statusSource: 'registry', activityHint: 'shell',
            parkedSummary: 'waiting on the build', transport: 'disconnected', hostOffline: 'studio', usageLimit: 'over limit', size: '9px', bare: true,
        }]);
    });

    test('a flat running row reads its `status` and its name locates the transport', () => {
        face({ row: { name: 'cc_flat', status: 'working', unread: false } });
        expect(seen[0]).toMatchObject({ status: 'working', unread: false, startupGate: null, statusSource: null, transport: null });
    });

    test('pre-read facts (the sidebar plan, a menu entry) arrive whole', () => {
        face({ facts: { family: null, status: 'idle', unread: true, startupGate: 'ready', statusSource: 'transcript', activityHint: null, parkedSummary: 'p', transport: 'connected', hostOffline: 'h', usageLimit: 'l' } });
        expect(seen[0]).toMatchObject({ status: 'idle', unread: true, startupGate: 'ready', statusSource: 'transcript', parkedSummary: 'p', transport: 'connected', hostOffline: 'h', usageLimit: 'l' });
    });

    test('every signal prop StatusLed declares is one the face passes', () => {
        const src = fs.readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'StatusLed.svelte'), 'utf8');
        const body = src.slice(src.indexOf('interface Props {'), src.indexOf('let {', src.indexOf('interface Props {')));
        const declared = [...body.matchAll(/^\s{8}(\w+)\?:/gm)].map((m) => m[1]!);
        expect(declared.length).toBeGreaterThan(8);
        face({ row: ROW });
        const passed = Object.keys(seen[0]!);
        expect(declared.filter((k) => k !== 'showLabel' && !passed.includes(k))).toEqual([]);
    });
});

describe('SessionFace behaviours around the light', () => {
    test('a lifecycle outranks the probe: an ended row is stopped, a sleeping one asleep with only its unread flag', () => {
        face({ row: ROW, lifecycle: 'stopped' });
        expect(seen[0]).toMatchObject({ status: 'stopped', unread: false, startupGate: null, statusSource: null, hostOffline: null });
        unmount(app!);
        seen.length = 0;
        app = null;
        face({ row: ROW, lifecycle: 'asleep' });
        expect(seen[0]).toMatchObject({ status: 'asleep', unread: true, activityHint: null });
    });

    test('a shell session draws no light, and an undetermined family keeps one', () => {
        face({ row: { ...ROW, agent_family: 'shell' } });
        expect(seen).toEqual([]);
        unmount(app!);
        app = null;
        face({ row: { ...ROW, agent_family: null } });
        expect(seen).toHaveLength(1);
    });

    test('the name rides after the light in the caller\'s class, and is absent unless given', () => {
        const withName = face({ row: ROW, name: 'api work', nameClass: 'x-name' });
        expect(withName.querySelector('span.x-name')?.textContent).toBe('api work');
        unmount(app!);
        app = null;
        expect(face({ row: ROW }).querySelector('span')).toBeNull();
    });
});
