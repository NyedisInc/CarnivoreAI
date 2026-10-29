import { describe, expect, test } from 'vitest';

import * as Led from './led';
import { ledHtmlForStatus } from './status-dot';
import { legacy } from './led-legacy-fixture';

describe('byte-identical to the legacy renderer', () => {
    const STATUSES = [
        'working',
        'working_subagent',
        'running',
        'question',
        'notice',
        'finished_unread',
        'idle',
        'dead',
        'stopped',
        'asleep',
        'unknown',
        undefined,
        'a-state-from-2030',
    ];
    const SOURCES = [
        undefined,
        'registry',
        'pane',
        'hook',
        'transcript',
        'seed_row',
        'tmux',
        'none',
        'not-a-source',
    ];
    const GATES = [undefined, 'ready', 'awaiting_startup_prompt', 'unknown'];
    const TRANSPORTS = [undefined, 'connected', 'disconnected', 'reconnecting'];
    const HINTS = [undefined, null, 'shell', 'not-a-hint'];

    test('the legacy files load in a bare sandbox', () => {
        const api = legacy();
        expect(typeof api.dotHtml).toBe('function');
        expect(typeof api.ledStateFor).toBe('function');
    });

    test('ledHtmlForStatus matches SessionStatusUI.dotHtml over the whole matrix', () => {
        const api = legacy();
        let compared = 0;
        for (const status of STATUSES) {
            for (const unread of [true, false, undefined]) {
                for (const startup_gate of GATES) {
                    for (const status_source of SOURCES) {
                        for (const transport of TRANSPORTS) {
                            for (const activity_hint of HINTS) {
                                const signals = {
                                    unread,
                                    startup_gate,
                                    status_source,
                                    transport,
                                    activity_hint,
                                };
                                const mine = ledHtmlForStatus(status, signals);
                                const theirs = api.dotHtml(status, signals);
                                expect(
                                    mine,
                                    `status=${status} unread=${unread} gate=${startup_gate} source=${status_source} transport=${transport} hint=${activity_hint}`,
                                ).toBe(theirs);
                                compared++;
                            }
                        }
                    }
                }
            }
        }
        expect(compared).toBe(
            STATUSES.length *
                3 *
                GATES.length *
                SOURCES.length *
                TRANSPORTS.length *
                HINTS.length,
        );
        expect(compared).toBeGreaterThan(1000);
    });

    test('the hint reaches the tooltip in BOTH trees, and only the tooltip', () => {
        const api = legacy();
        const without = ledHtmlForStatus('idle', { unread: false });
        const withHint = ledHtmlForStatus('idle', {
            unread: false,
            activity_hint: 'shell',
        });
        expect(withHint).not.toBe(without);
        expect(withHint).toContain('shell still running');
        expect(api.dotHtml('idle', { unread: false, activity_hint: 'shell' })).toBe(
            withHint,
        );
        expect(withHint.replace(/ (title|aria-label)="[^"]*"/g, '')).toBe(
            without.replace(/ (title|aria-label)="[^"]*"/g, ''),
        );
        expect(
            ledHtmlForStatus('idle', { unread: false, activity_hint: 'not-a-hint' }),
        ).toBe(without);
    });

    test('the `size` passthrough matches too, including the values it drops', () => {
        const api = legacy();
        for (const size of ['9px', '18px', '1.5rem', 'red; background:url(x)', '']) {
            const signals = { unread: false, size };
            expect(ledHtmlForStatus('idle', signals), `size=${size}`).toBe(
                api.dotHtml('idle', signals),
            );
        }
    });

    test('a caller passing no signals at all matches too', () => {
        const api = legacy();
        for (const status of STATUSES) {
            expect(ledHtmlForStatus(status), `status=${status}`).toBe(
                api.dotHtml(status),
            );
            expect(ledHtmlForStatus(status, null), `status=${status} null`).toBe(
                api.dotHtml(status, null),
            );
        }
    });

    test('the low-level ledHtml matches the legacy one over its own matrix', () => {
        const api = legacy();
        for (const inner of [...Led.INNER_STATES, 'banana', undefined]) {
            for (const outer of [...Led.OUTER_STATES, 'kumquat', undefined]) {
                for (const extraClass of [undefined, 'status-dot', '" onload="x']) {
                    const opts = { inner, outer, extraClass };
                    expect(
                        Led.ledHtml(opts),
                        `${String(inner)}/${String(outer)}/${String(extraClass)}`,
                    ).toBe(api.ledHtml(opts));
                }
            }
        }
    });

    test('NEGATIVE CONTROL: the comparison can actually fail', () => {
        const api = legacy();
        expect(ledHtmlForStatus('idle', { unread: false })).not.toBe(
            api.dotHtml('idle', { unread: true }),
        );
        expect(ledHtmlForStatus('working')).not.toBe(api.dotHtml('dead'));
    });
});
