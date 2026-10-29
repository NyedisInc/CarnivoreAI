/** @vitest-environment jsdom */
import { flushSync, mount, unmount } from 'svelte';
import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { loadLegacyDrawer } from './legacy-fixture';
import { rowHost } from './row-host';
import { buildRowPlan } from './row-plan';
import SessionRow from './SessionRow.svelte';

let mounted: Array<{ app: unknown; target: HTMLElement }> = [];

beforeAll(() => { loadLegacyDrawer(); });

afterEach(() => {
    for (const m of mounted) { unmount(m.app as never); m.target.remove(); }
    mounted = [];
});

function listRow(status: string, unread: boolean): Record<string, unknown> {
    return {
        name: 'cloude_oneflag', label: 'one flag', status, unread, is_active: false, is_this_tab: false,
        created_by_cloude: true, created_at_epoch: 1788444912, session_id: 'ses_oneflag', startup_gate: 'ready',
        agent_family: 'claude', agent_family_source: 'launched', pinned_theme: null, last_work_at: null,
    };
}

function light(r: Record<string, unknown>): { inner: string | null; outer: string | null } {
    const target = document.body.appendChild(document.createElement('div'));
    const app = mount(SessionRow, { target, props: { p: buildRowPlan(r as never, 'cozy', undefined, null, rowHost()) as never } });
    flushSync();
    mounted.push({ app, target });
    const led = target.querySelector('[data-inner]');
    return { inner: led?.getAttribute('data-inner') ?? null, outer: led?.getAttribute('data-outer') ?? null };
}

describe('the drawer row paints unread from the one field', () => {
    it('an idle unread row paints the green dot and the still unread ring', () => {
        expect(light(listRow('idle', true))).toEqual({ inner: 'done', outer: 'unread' });
    });

    it('NEGATIVE CONTROL: an idle row with nothing waiting paints the grey read dot and a steady ring', () => {
        expect(light(listRow('idle', false))).toEqual({ inner: 'idle', outer: 'steady' });
    });

    it('a working row rings active whatever the flag says', () => {
        expect(light(listRow('working', false)).outer).toBe('active');
        expect(light(listRow('working', true)).outer).toBe('active');
    });

    it('a dead pane is never painted as something to read', () => {
        expect(light(listRow('dead', true))).toEqual({ inner: 'dead', outer: 'off' });
    });

    it('the unread ring appears exactly where a turn finished and nothing runs', () => {
        for (const status of ['idle', 'working', 'finished_unread', 'unknown', 'dead']) {
            for (const unread of [true, false]) {
                const resting = status === 'finished_unread' || (status === 'idle' && unread);
                const { outer } = light(listRow(status, unread));
                if (resting) expect(outer, `${status}/unread=${unread}`).toBe('unread');
                else expect(outer, `${status}/unread=${unread}`).not.toBe('unread');
            }
        }
    });
});
