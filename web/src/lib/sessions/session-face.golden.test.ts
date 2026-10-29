/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import LedgerSessions from '../ledger/LedgerSessions.svelte';
import RowLed from '../sessions-page/RowLed.svelte';

const SIGNALS = {
    activity_status: 'working', status: 'working', unread: true, startup_gate: 'ready', status_source: 'registry',
    activity_hint: 'shell', parked_summary: 'waiting on the build', agent_family: 'claude', agent_family_source: 'wrapper',
};
const VARIANTS: Record<string, Record<string, unknown>> = {
    full: {},
    'host-down': { host_key: 'peer-1', host_label: 'studio', host_state: 'disconnected' },
    limit: { usage_limit: { resets_at: null } },
};

const rowFor = (variant: string): Record<string, unknown> => ({
    ...SIGNALS, name: `cc_${variant}`, label: `face ${variant}`, tmux_session: `cc_${variant}`, created_by_cloude: true,
    created_at_epoch: 1_700_000_000, session_row_id: 7, session_uuid: `u-${variant}`, session: { id: `ses_${variant}` },
    ...VARIANTS[variant],
});

let mounted: Record<string, unknown> | null = null;
afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
});

async function paint(component: unknown, props: Record<string, unknown>): Promise<HTMLElement> {
    const target = document.createElement('div');
    document.body.append(target);
    mounted = mount(component as never, { target, props });
    for (let i = 0; i < 6; i += 1) await Promise.resolve();
    await tick();
    flushSync();
    return target;
}

function face(root: HTMLElement, nameSel?: string): string {
    const leds = [...root.querySelectorAll('[data-inner]')].map((n) => n.outerHTML);
    const name = nameSel ? [...root.querySelectorAll(nameSel)].map((n) => n.outerHTML) : [];
    return [...leds, ...name].join('\n').replace(/ svelte-[a-z0-9]+/g, '');
}

describe('session face goldens', () => {
    test('every surface draws the face it drew before SessionFace', async () => {
        const out: string[] = [];
        for (const v of Object.keys(VARIANTS)) {
            const r = rowFor(v);
            const lp = (c: unknown, p: Record<string, unknown>, sel?: string) => paint(c, p).then((root) => face(root, sel));
            out.push(`## ${v} / ledger sessions\n${await lp(LedgerSessions, { rows: [r], t: (k: string) => k, onOpen: () => {} }, '.ledger-sessions__name')}`);
            unmount(mounted!); mounted = null;
            out.push(`## ${v} / sessions page led\n${await lp(RowLed, { row: { provider: 'claude', s: { state: 'live' } }, live: r, asleepUnread: false })}`);
            unmount(mounted!); mounted = null;
        }
        out.push(`## asleep / sessions page led\n${await paint(RowLed, { row: { provider: 'claude', s: { state: 'asleep' } }, live: undefined, asleepUnread: true }).then((root) => face(root))}`);
        await expect(out.join('\n\n') + '\n').toMatchFileSnapshot('./__goldens__/session-face.html');
    });
});
