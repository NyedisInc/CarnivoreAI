import { describe, expect, test } from 'vitest';

import * as Led from './led';

function rawAttr(html: string, attr: string): string | null {
    const start = html.indexOf(`${attr}="`);
    if (start === -1) return null;
    const from = start + attr.length + 2;
    const end = html.indexOf('"', from);
    if (end === -1) return null;
    return html.slice(from, end);
}


describe('the vocabularies', () => {
    test('both vocabularies are exported and non-empty', () => {
        expect(Array.isArray(Led.INNER_STATES)).toBe(true);
        expect(Led.INNER_STATES.length).toBeGreaterThan(0);
        expect(Array.isArray(Led.OUTER_STATES)).toBe(true);
        expect(Led.OUTER_STATES.length).toBeGreaterThan(0);
    });


    test('the inner vocabulary is exactly the twelve documented states', () => {
        expect([...Led.INNER_STATES]).toEqual([
            'working',
            'waiting-permission',
            'waiting-input',
            'notice',
            'idle',
            'done',
            'dead',
            'disconnected',
            'asleep',
            'asleep-unread',
            'limit',
            'unknown',
        ]);
    });

    test('a flagged asleep session is the unread moon, with no ring (issue #749)', () => {
        expect(Led.ledStateFor({ activity_status: 'asleep', unread: true, transport: 'disconnected' }))
            .toEqual({ inner: 'asleep-unread', outer: 'off' });
        expect(Led.ledStateFor({ activity_status: 'asleep', unread: false }))
            .toEqual({ inner: 'asleep', outer: 'off' });
        expect(Led.ledStateFor({ activity_status: 'idle', unread: true }))
            .toEqual({ inner: 'done', outer: 'unread' });
        expect(Led.ledLabel('asleep-unread', 'off')).toBe('asleep, flagged unread - wake it to follow up');
    });

    test('an asleep session is the moon whatever the socket says', () => {
        expect(Led.ledStateFor({ activity_status: 'asleep', transport: 'disconnected' }))
            .toEqual({ inner: 'asleep', outer: 'off' });
        expect(Led.ledStateFor({ activity_status: 'idle', transport: 'disconnected' }).inner)
            .toBe('disconnected');
    });

    test('the outer vocabulary is exactly the five documented states', () => {
        expect([...Led.OUTER_STATES]).toEqual([
            'active',
            'steady',
            'unread',
            'off',
            'dim',
        ]);
    });

    test('THE RING CARRIES UNREAD - the owner ruled for it, 2026-09-09', () => {
        expect([...Led.OUTER_STATES].indexOf('unread')).toBeGreaterThanOrEqual(0);
    });

    test('EXACTLY THE FINISHED-TURN STATES PRODUCE AN unread RING', () => {
        const withRing: string[] = [];
        const statuses = [
            'working',
            'working_subagent',
            'running',
            'question',
            'notice',
            'finished_unread',
            'idle',
            'dead',
            'stopped',
            'unknown',
            undefined,
            'a-state-from-2030',
        ];
        for (const status of statuses) {
            for (const gate of [undefined, 'awaiting_startup_prompt', 'unknown']) {
                const led = Led.ledStateFor({
                    activity_status: status,
                    unread: true,
                    startup_gate: gate,
                });
                if (led.outer === 'unread') withRing.push(`${status}/${gate}`);
                expect(
                    [...Led.OUTER_STATES].indexOf(led.outer),
                    `${status} produced an outer value outside the vocabulary`,
                ).toBeGreaterThanOrEqual(0);
            }
        }
        expect(withRing).toEqual([
            'finished_unread/undefined',
            'finished_unread/unknown',
            'idle/undefined',
            'idle/unknown',
        ]);
    });

    test('NOTHING AT REST BREATHES', () => {
        const breathing: string[] = [];
        for (const status of [
            'working',
            'working_subagent',
            'running',
            'question',
            'notice',
            'finished_unread',
            'idle',
            'dead',
            'unknown',
        ]) {
            if (
                Led.ledStateFor({ activity_status: status, unread: true }).outer ===
                'active'
            ) {
                breathing.push(status);
            }
        }
        expect(breathing).toEqual([
            'working',
            'working_subagent',
            'running',
            'question',
            'notice',
        ]);
        for (const atRest of ['finished_unread', 'idle', 'dead', 'unknown']) {
            expect(
                Led.ledStateFor({ activity_status: atRest, unread: true }).outer,
                `${atRest} must not animate`,
            ).not.toBe('active');
        }
    });

    test('the exported vocabularies cannot be mutated by a caller', () => {
        expect(() => {
            (Led.INNER_STATES as unknown as string[]).push('bogus');
        }).toThrow();
        expect([...Led.INNER_STATES].indexOf('bogus' as never)).toBe(-1);
    });
});

// ---- markup per state -------------------------------------------------

describe('markup per state', () => {
    test('every inner x outer combination renders a labelled LED', () => {
        for (const inner of Led.INNER_STATES) {
            for (const outer of Led.OUTER_STATES) {
                const html = Led.ledHtml({ inner, outer });
                expect(rawAttr(html, 'data-inner'), `inner ${inner}`).toBe(inner);
                expect(rawAttr(html, 'data-outer'), `outer ${outer}`).toBe(outer);
                expect(html).toContain('class="status-led"');
                expect(html).toContain('role="img"');
                const label = rawAttr(html, 'aria-label');
                expect(label, `labelled: ${inner}/${outer}`).toBeTruthy();
                expect(rawAttr(html, 'title')).toBe(label);
            }
        }
    });

    test('an unknown inner or outer value is clamped, never emitted raw', () => {
        const html = Led.ledHtml({ inner: 'banana', outer: 'kumquat' });
        expect(rawAttr(html, 'data-inner')).toBe('unknown');
        expect(rawAttr(html, 'data-outer')).toBe('dim');
    });

    test('no arguments at all still renders a valid not-measured LED', () => {
        const html = Led.ledHtml();
        expect(rawAttr(html, 'data-inner')).toBe('unknown');
        expect(rawAttr(html, 'data-outer')).toBe('dim');
    });

    test('ledHtml escapes a hostile title rather than interpolating it raw', () => {
        const html = Led.ledHtml({
            inner: 'done',
            outer: 'steady',
            title: '"><img src=x>',
        });
        expect(html).not.toContain('<img');
        expect(html).toContain('&quot;');
    });

    test('size is accepted only as a plain CSS length', () => {
        expect(Led.ledHtml({ size: '18px' })).toContain('--led-size: 18px');
        expect(Led.ledHtml({ size: '1.5rem' })).toContain('--led-size: 1.5rem');
        expect(Led.ledHtml({ size: 'red; background:url(x)' })).not.toContain('style=');
        expect(Led.ledHtml({ size: 12 })).not.toContain('style=');
    });

    test('extraClass is accepted only as plain class names', () => {
        expect(Led.ledHtml({ extraClass: 'status-dot status-dot--dead' })).toContain(
            'class="status-dot status-dot--dead status-led"',
        );
        expect(Led.ledHtml({ extraClass: '" onload="x' })).toContain(
            'class="status-led"',
        );
    });
});

// ---- the mapping from server signals ----------------------------------

describe('the mapping from server signals', () => {
    test('dead outranks everything, and a corpse never glows', () => {
        expect(Led.ledStateFor({ activity_status: 'dead', unread: true })).toEqual({
            inner: 'dead',
            outer: 'off',
        });
        // `stopped` is a session that is GONE rather than a held-open
        expect(Led.ledStateFor({ activity_status: 'stopped', unread: true })).toEqual({
            inner: 'dead',
            outer: 'off',
        });
    });

    test('a startup prompt is waiting-input even when the status says nothing', () => {
        expect(
            Led.ledStateFor({
                activity_status: 'idle',
                startup_gate: 'awaiting_startup_prompt',
            }),
        ).toEqual({ inner: 'waiting-input', outer: 'active' });
    });

    test('a startup gate that could not be measured does not claim anything', () => {
        expect(
            Led.ledStateFor({ activity_status: 'idle', startup_gate: 'unknown' }),
        ).toEqual({ inner: 'idle', outer: 'steady' });
    });

    test('question maps to waiting-permission - the agent is stopped', () => {
        expect(Led.ledStateFor({ activity_status: 'question' })).toEqual({
            inner: 'waiting-permission',
            outer: 'active',
        });
    });

    test('notice has its OWN inner state - working, but wanting you', () => {
        expect(Led.ledStateFor({ activity_status: 'notice' })).toEqual({
            inner: 'notice',
            outer: 'active',
        });
    });

    test('question and notice do not paint the same inner dot', () => {
        expect(Led.ledStateFor({ activity_status: 'question' }).inner).not.toBe(
            Led.ledStateFor({ activity_status: 'notice' }).inner,
        );
    });

    test('a startup prompt is STOPPED, and so is not a notice', () => {
        const gated = Led.ledStateFor({
            activity_status: 'idle',
            startup_gate: 'awaiting_startup_prompt',
        }).inner;
        expect(gated).toBe('waiting-input');
        expect(gated).not.toBe(Led.ledStateFor({ activity_status: 'notice' }).inner);
    });

    test('an unread flag never downgrades a blocking permission prompt', () => {
        expect(
            Led.ledStateFor({ activity_status: 'question', unread: true }),
        ).toEqual({ inner: 'waiting-permission', outer: 'active' });
    });

    test('working and working_subagent share the inner dot', () => {
        expect(Led.ledStateFor({ activity_status: 'working' }).inner).toBe('working');
        expect(Led.ledStateFor({ activity_status: 'working_subagent' }).inner).toBe(
            'working',
        );
    });

    test('the legacy `running` spelling still maps to working', () => {
        expect(Led.ledStateFor({ activity_status: 'running' }).inner).toBe('working');
    });

    test('UNREAD RIDES THE RING, and a working session never wears it', () => {
        const busy = Led.ledStateFor({ activity_status: 'working', unread: true });
        expect(busy).toEqual({ inner: 'working', outer: 'active' });

        const rested = Led.ledStateFor({ activity_status: 'idle', unread: true });
        expect(rested).toEqual({ inner: 'done', outer: 'unread' });

        const read = Led.ledStateFor({ activity_status: 'idle', unread: false });
        expect(read).toEqual({ inner: 'idle', outer: 'steady' });
        expect(read.outer).not.toBe(rested.outer);
    });

    test('idle and seen is its own grey dot in a lit-but-still ring', () => {
        expect(Led.ledStateFor({ activity_status: 'idle' })).toEqual({
            inner: 'idle',
            outer: 'steady',
        });
    });

    test('idle is not done, and not unknown either', () => {
        const idle = Led.ledStateFor({ activity_status: 'idle' });
        expect(idle.inner).not.toBe('done');
        expect(idle.inner).not.toBe('unknown');
        expect(idle.inner).toBe('idle');
    });

    test('finished_unread is the green RING - the chat itself is at rest', () => {
        expect(Led.ledStateFor({ activity_status: 'finished_unread' })).toEqual({
            inner: 'done',
            outer: 'unread',
        });
    });

    test('finished_unread and idle differ in BOTH rings', () => {
        const unread = Led.ledStateFor({ activity_status: 'finished_unread' });
        const read = Led.ledStateFor({ activity_status: 'idle' });
        expect(unread.outer).not.toBe(read.outer);
        expect(unread.inner).not.toBe(read.inner);
    });

    test('A DEAD TRANSPORT OUTRANKS EVERYTHING, including a working row', () => {
        expect(
            Led.ledStateFor({ activity_status: 'working', transport: 'disconnected' }),
        ).toEqual({ inner: 'disconnected', outer: 'off' });
        for (const t of [undefined, 'connected', 'unknown', 'reconnecting']) {
            expect(
                Led.ledStateFor({ activity_status: 'working', transport: t }).inner,
                `transport=${t} must fall through`,
            ).toBe('working');
        }
    });

    test('UNKNOWN IS NOT DONE - the false green this project keeps paying for', () => {
        expect(Led.ledStateFor({ activity_status: 'unknown' }).inner).toBe('unknown');
        expect(Led.ledStateFor({}).inner).toBe('unknown');
        expect(Led.ledStateFor(null).inner).toBe('unknown');
        expect(Led.ledStateFor({ activity_status: 'a-state-from-2030' }).inner).toBe(
            'unknown',
        );
    });

    test('an unmeasured session stays unmeasured even with the flag set', () => {
        expect(Led.ledStateFor({ activity_status: 'unknown', unread: true })).toEqual({
            inner: 'unknown',
            outer: 'dim',
        });
    });
});
