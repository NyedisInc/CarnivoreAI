/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import { createI18n } from '../../../../client/js/i18n/runtime.js';
import type { SessionListItem, Translate } from '../sessions/types';
import type { PeerRow } from './federation-api';
import PeerSessions from './PeerSessions.svelte';

const en = createI18n({ locale: 'en' }) as { t: Translate };
const t: Translate = (key, params) => en.t(key, params);

let mounted: Record<string, unknown> | null = null;
afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
});

const peer = (over: Partial<PeerRow> = {}): PeerRow => ({
    key: 'peer-1', label: 'hosta', peer_install_id: 'iid-1', fid: 'f', initiator: true, state: 'connected', protocol: 1, ...over,
});
const item = (host_key: string, tmux: string, over: Record<string, unknown> = {}): SessionListItem =>
    ({ host_key, tmux_session: tmux, label: tmux, session: { id: `id-${tmux}` }, activity_status: 'idle', project_name: 'cloude-projects', ...over }) as SessionListItem;

async function pane(p: PeerRow, rows: SessionListItem[], onOpen = vi.fn()): Promise<HTMLElement> {
    const target = document.createElement('div');
    document.body.append(target);
    mounted = mount(PeerSessions, { target, props: { peer: p, t, load: async () => rows, onOpen } });
    for (let i = 0; i < 6; i += 1) await Promise.resolve();
    await tick();
    flushSync();
    return target;
}

describe('peer sessions', () => {
    test('lists only this peer\'s rows, with project, and a click opens by ids', async () => {
        const onOpen = vi.fn();
        const root = await pane(peer(), [item('peer-1', 'HostaTest'), item('other', 'Elsewhere'), item('local', 'Mine')], onOpen);
        const rows = [...root.querySelectorAll('[data-peer-session]')];
        expect(rows.map((r) => r.getAttribute('data-peer-session'))).toEqual(['HostaTest']);
        expect(rows[0]!.textContent).toContain('cloude-projects');
        (rows[0] as HTMLElement).click();
        expect(onOpen).toHaveBeenCalledWith('id-HostaTest', 'HostaTest');
    });

    test('none for this host says so', async () => {
        const root = await pane(peer(), [item('other', 'Elsewhere')]);
        expect(root.querySelector('[data-peer-sessions-empty]')).not.toBeNull();
    });

    test('a down link shows disconnected on each row', async () => {
        const root = await pane(peer({ state: 'disconnected' }), [item('peer-1', 'HostaTest')]);
        expect(root.querySelector('[data-peer-session-down]')!.textContent).toBe('disconnected');
    });
});
