/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const faces: Array<Record<string, unknown> | null> = [];

vi.mock('../sessions/SessionFace.svelte', () => ({
    default: (_anchor: unknown, props: { member?: unknown }) => { faces.push((props.member as Record<string, unknown> | null | undefined) ?? null); },
}));

import RowLed from './RowLed.svelte';
import { registerSwarmRoster, unregisterSwarmRoster } from '../../cplugs/sdk/swarm-roster.svelte';

const ROW = { provider: 'claude', s: { state: 'live', session_uuid: 'u-7' } };
let app: Record<string, unknown> | null = null;

afterEach(() => {
    if (app) unmount(app);
    app = null;
    faces.length = 0;
    unregisterSwarmRoster();
    document.body.innerHTML = '';
});

function drawRow(): void {
    const target = document.createElement('div');
    document.body.append(target);
    app = mount(RowLed as never, { target, props: { row: ROW, live: undefined, asleepUnread: false } });
    flushSync();
}

describe('RowLed and the Swarm roster', () => {
    test('with the plugin on, a session on the roster is a member', () => {
        registerSwarmRoster({ agents: () => [{ id: 7, rank: 'feature', session_uuid: 'u-7' }], refresh: async () => {} });
        drawRow();
        expect(faces).toEqual([{ agentId: 7, rank: 'feature', seed: 7 }]);
    });

    test('with the plugin off, the row draws as a plain session and nothing throws', () => {
        drawRow();
        expect(faces).toEqual([null]);
    });
});
