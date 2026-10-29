import { describe, expect, it } from 'vitest';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { failureLine, failureReason } from './failures';

const i18n = createI18n({ locale: 'en' }) as { t(key: string, params?: Record<string, unknown> | null): string };
const t = (key: string, params?: Record<string, unknown> | null): string => i18n.t(key, params);
const OFFLINE = 'the catalog could not be reached. press refresh to try again.';

describe('failureLine', () => {
    it('reads the offline line for an unreachable host on every source and action', () => {
        const dropped = Object.assign(new Error('backend unreachable'), { name: 'ApiError', status: 0, code: 'unreachable' });
        for (const source of ['mine', 'folders', 'facts', 'rules', 'limits', 'appeal', 'withdraw', 'check', 'send'] as const) {
            expect(failureLine(source, dropped, t), source).toBe(OFFLINE);
            expect(failureLine(source, new TypeError('Failed to fetch'), t), source).toBe(OFFLINE);
        }
    });

    it('a withdraw 409 not_withdrawable and a catalog fault each read a plain sentence', () => {
        expect(failureLine('withdraw', Object.assign(new Error('x'), { status: 409, detail: { code: 'not_withdrawable' } }), t)).toContain('can no longer be withdrawn');
        expect(failureLine('rules', Object.assign(new Error('x'), { status: 500 }), t)).toBe('the catalog had a problem. press refresh to try again.');
        expect(failureLine('facts', Object.assign(new Error('x'), { status: 503 }), t)).toBe(OFFLINE);
    });

    it('any other failure keeps its source line with the reason, and the reason is exposed for the folder list', () => {
        expect(failureLine('folders', new Error('boom'), t)).toBe('some of your folders could not be listed: boom');
        expect(failureReason('folders', new Error('boom'), t)).toBe('boom');
        expect(failureReason('folders', new TypeError('Failed to fetch'), t)).toBe('');
    });

    it('the real nested host refusal reads a plain line, never "the server answered" (X6-2)', () => {
        const nested = (status: number, code: string, sentence?: string) =>
            Object.assign(new Error(sentence ?? `the server answered ${status}`), { status, detail: { code, ...(sentence ? { detail: sentence } : {}) } });
        expect(failureLine('appeal', nested(409, 'appeal_limit', 'no appeals left'), t)).toBe('the appeal was not sent: no appeals are left for this version.');
        expect(failureLine('appeal', nested(409, 'not_rejected'), t)).toBe('the appeal was not sent: only a rejected version can be appealed.');
        expect(failureLine('withdraw', nested(409, 'not_withdrawable'), t)).toContain('can no longer be withdrawn');
        for (const source of ['withdraw', 'appeal'] as const) {
            const bare = Object.assign(new Error('the server answered 409'), { status: 409 });
            const line = failureLine(source, bare, t);
            expect(line).toBe('that did not go through. press refresh and try again.');
            expect(line).not.toContain('server answered');
        }
    });

    it('a 500 on the folder list reads the folders line, not the catalog line (X6-23)', () => {
        const line = failureLine('folders', Object.assign(new Error('the server answered 500'), { status: 500 }), t);
        expect(line).toContain('some of your folders could not be listed');
        expect(line).not.toContain('catalog');
        expect(failureLine('folders', Object.assign(new Error('x'), { status: 0, code: 'unreachable' }), t)).toBe(OFFLINE);
    });
});

describe('an unmapped refusal code (X7-5)', () => {
    const GENERIC = 'that did not go through. press refresh and try again.';
    const refused = (status: number, code: string, sentence?: string) =>
        Object.assign(new Error(`the server answered ${status}`), { status, detail: { code, ...(sentence ? { detail: sentence } : {}) } });
    it('prints the generic line, never the raw code or "no explanation", for every action and a read', () => {
        for (const source of ['appeal', 'send', 'register', 'withdraw', 'facts', 'report'] as const) {
            for (const status of [409, 429]) {
                const line = failureLine(source, refused(status, 'a_code_nobody_wrote_a_line_for'), t);
                expect(line, `${source} ${status}`).toBe(GENERIC);
                expect(line).not.toContain('a_code_nobody');
                expect(line).not.toContain('no explanation');
            }
        }
    });
    it('a host sentence in the body still wins', () => {
        expect(failureLine('appeal', refused(409, 'a_code_nobody_wrote_a_line_for', 'the host says wait a day'), t)).toBe('the host says wait a day');
    });
});
