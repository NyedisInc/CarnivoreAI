import { describe, expect, test } from 'vitest';

import { ledHtmlForStatus } from './status-dot';
import { usageLimitLabel } from './led';
import { legacy } from './led-legacy-fixture';

const STATUSES = ['working', 'working_subagent', 'question', 'notice', 'finished_unread', 'idle', 'dead', 'stopped', 'asleep', 'unknown', undefined];
const LIMIT = { kind: 'weekly', resets_at: '2026-10-21T01:00:00+00:00', message: 'You hit your weekly limit', since: '2026-10-17T12:00:00+00:00' };

describe('usage limit red skull', () => {
    test('both trees build the same label, with and without a reset time', () => {
        const api = legacy();
        for (const row of [{ usage_limit: LIMIT }, { usage_limit: { ...LIMIT, resets_at: null } }, { usage_limit: { ...LIMIT, resets_at: 'garbage' } }, { usage_limit: null }, {}, null]) {
            expect(usageLimitLabel(row)).toBe(api.usageLimitLabel(row));
        }
        expect(usageLimitLabel({ usage_limit: { ...LIMIT, resets_at: null } })).toBe('over limit');
        expect(usageLimitLabel({ usage_limit: LIMIT })).toMatch(/^over limit, resets [a-z]{3} \d{1,2} \d{1,2}(:\d\d)?(am|pm)$/);
        expect(usageLimitLabel({})).toBeNull();
    });

    test('the skull outranks every status, startup gate and unread flag, and is byte-identical across trees', () => {
        const api = legacy();
        const label = usageLimitLabel({ usage_limit: LIMIT }) as string;
        let skulls = 0;
        for (const status of STATUSES) {
            for (const unread of [true, false]) {
                for (const startup_gate of [undefined, 'awaiting_startup_prompt']) {
                    const signals = { unread, startup_gate, usage_limit: label };
                    const mine = ledHtmlForStatus(status, signals);
                    expect(mine).toBe(api.dotHtml(status, signals));
                    if (status === 'dead' || status === 'stopped') {
                        expect(mine).toContain('data-inner="dead"');
                    } else if (status === 'asleep') {
                        expect(mine).toContain('data-inner="asleep');
                    } else {
                        expect(mine).toContain('data-inner="limit"');
                        expect(mine).toContain(`aria-label="${label}"`);
                        skulls++;
                    }
                }
            }
        }
        expect(skulls).toBe(8 * 4);
    });

    test('a dropped transport and an unreachable Mac keep their red; the skull sits under them', () => {
        const api = legacy();
        const signals = { transport: 'disconnected', usage_limit: 'over limit' };
        expect(ledHtmlForStatus('working', signals)).toContain('data-inner="disconnected"');
        expect(ledHtmlForStatus('working', signals)).toBe(api.dotHtml('working', signals));
        const off = { host_offline: 'studio', usage_limit: 'over limit' };
        expect(ledHtmlForStatus('working', off)).toContain('data-inner="disconnected"');
        expect(ledHtmlForStatus('working', off)).toBe(api.dotHtml('working', off));
    });

    test('a null or absent usage_limit paints exactly as before', () => {
        const api = legacy();
        for (const status of STATUSES) {
            for (const unread of [true, false]) {
                const plain = ledHtmlForStatus(status, { unread });
                expect(ledHtmlForStatus(status, { unread, usage_limit: null })).toBe(plain);
                expect(api.dotHtml(status, { unread, usage_limit: null })).toBe(plain);
                expect(plain).not.toContain('data-inner="limit"');
            }
        }
    });
});
