/** @vitest-environment jsdom */
import { flushSync, mount, unmount } from 'svelte';
import { describe, expect, test } from 'vitest';

import StatusLed from './StatusLed.svelte';
import { loadLegacyDrawer } from './sidebar-shell/legacy-fixture';
import { ledHtmlForStatus } from './status-dot';

const STATUSES = [
    'working', 'working_subagent', 'question', 'notice', 'finished_unread', 'idle', 'dead',
    'asleep', 'unknown', undefined, 'a-state-from-2030',
];
const SOURCES = [undefined, 'registry', 'pane', 'transcript', 'tmux', 'none', 'not-a-source'];
const GATES = [undefined, 'ready', 'awaiting_startup_prompt'];
const TRANSPORTS = [undefined, 'connected', 'disconnected'];
const HINTS = [undefined, 'shell', 'not-a-hint'];

function parsed(html: string): string {
    const el = document.createElement('div');
    el.innerHTML = html;
    return el.innerHTML;
}

function drawBare(props: Record<string, unknown>): string {
    const target = document.createElement('div');
    const app = mount(StatusLed, { target, props: { ...props, bare: true } });
    flushSync();
    const html = target.innerHTML.replace(/<!--[^>]*-->/g, '');
    unmount(app);
    return html;
}

describe('the bare StatusLed', () => {
    test('matches ledHtmlForStatus and SessionStatusUI.dotHtml over the whole matrix', () => {
        const api = loadLegacyDrawer().SessionStatusUI;
        let compared = 0;
        for (const status of STATUSES) {
            for (const unread of [true, false]) {
                for (const startup_gate of GATES) {
                    for (const status_source of SOURCES) {
                        for (const transport of TRANSPORTS) {
                            for (const activity_hint of HINTS) {
                                const signals = { unread, startup_gate, status_source, transport, activity_hint };
                                const mine = drawBare({
                                    status, unread, startupGate: startup_gate, statusSource: status_source,
                                    transport, activityHint: activity_hint,
                                });
                                const where = `status=${status} unread=${unread} gate=${startup_gate} source=${status_source} transport=${transport} hint=${activity_hint}`;
                                expect(mine, where).toBe(parsed(ledHtmlForStatus(status, signals)));
                                expect(mine, where).toBe(parsed(api.dotHtml(status, signals)));
                                compared += 1;
                            }
                        }
                    }
                }
            }
        }
        expect(compared).toBe(STATUSES.length * 2 * GATES.length * SOURCES.length * TRANSPORTS.length * HINTS.length);
    });

    test('a bare light ignores a size (the drawer row never sizes its light)', () => {
        expect(drawBare({ status: 'idle', size: '9px' })).toBe(parsed(ledHtmlForStatus('idle')));
    });

    test('NEGATIVE CONTROL: the non-bare form is NOT the legacy string (it has a layout wrapper)', () => {
        const target = document.createElement('div');
        const app = mount(StatusLed, { target, props: { status: 'idle' } });
        flushSync();
        const html = target.innerHTML.replace(/<!--[^>]*-->/g, '');
        unmount(app);
        expect(html).not.toBe(parsed(ledHtmlForStatus('idle')));
        expect(html).toContain('status-led');
    });
});
