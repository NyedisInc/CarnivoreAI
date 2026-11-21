import { describe, expect, test } from 'vitest';

import { ledHtmlForStatus } from './status-dot';
import { ledStateFor, loginExpiredLabel } from './led';
import { legacy } from './led-legacy-fixture';

const STATUSES = ['working', 'working_subagent', 'question', 'notice', 'finished_unread', 'idle', 'dead', 'stopped', 'asleep', 'unknown', undefined];
const LOGIN = { message: 'Login reached its time limit · Please run /login', since: '2026-11-17T15:00:00.189000+00:00' };

describe('expired login notice', () => {
    test('both trees build the same label, and null stays null', () => {
        const api = legacy();
        for (const row of [{ login_expired: LOGIN }, { login_expired: { message: '', since: null } }, { login_expired: null }, {}, null]) {
            expect(loginExpiredLabel(row)).toBe(api.loginExpiredLabel(row));
        }
        expect(loginExpiredLabel({ login_expired: LOGIN })).toBe(`needs login - ${LOGIN.message}`);
        expect(loginExpiredLabel({ login_expired: { message: '', since: null } })).toBe('needs login');
        expect(loginExpiredLabel({ login_expired: null })).toBeNull();
        expect(loginExpiredLabel({})).toBeNull();
    });

    test('the notice outranks every live status and is byte-identical across trees', () => {
        const api = legacy();
        const label = loginExpiredLabel({ login_expired: LOGIN }) as string;
        let painted = 0;
        for (const status of STATUSES) {
            for (const unread of [true, false]) {
                const signals = { unread, login_expired: label };
                const mine = ledHtmlForStatus(status, signals);
                expect(mine).toBe(api.dotHtml(status, signals));
                if (status === 'dead' || status === 'stopped') {
                    expect(mine).toContain('data-inner="dead"');
                } else if (status === 'asleep') {
                    expect(mine).toContain('data-inner="asleep');
                } else {
                    expect(mine).toContain('data-inner="notice"');
                    expect(mine).toContain('data-outer="steady"');
                    expect(mine).toContain(`aria-label="${label}"`);
                    painted++;
                }
            }
        }
        expect(painted).toBe(8 * 2);
    });

    test('a dropped transport and the usage-limit skull outrank it; no signal paints as before', () => {
        expect(ledStateFor({ activity_status: 'idle', transport: 'disconnected', login_expired: 'needs login' }).inner).toBe('disconnected');
        expect(ledStateFor({ activity_status: 'idle', usage_limit: 'over limit', login_expired: 'needs login' }).inner).toBe('limit');
        expect(ledStateFor({ activity_status: 'idle', login_expired: null })).toEqual(ledStateFor({ activity_status: 'idle' }));
        expect(ledHtmlForStatus('idle', { login_expired: null })).toBe(ledHtmlForStatus('idle'));
    });
});
