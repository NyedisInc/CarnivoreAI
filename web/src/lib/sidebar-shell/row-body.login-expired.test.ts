import { describe, expect, test } from 'vitest';

import { stateWord } from './row-body';
import type { LedPlan } from './row-plan';

const LED = { status: 'idle', unread: false, startupGate: null, statusSource: null, activityHint: null, parkedSummary: null,
    transport: 'unknown', hostOffline: null, usageLimit: null, loginExpired: null } as unknown as LedPlan;

describe('sidebar row state word for an expired login', () => {
    test('says needs login, in the notice tone, while the login is expired', () => {
        expect(stateWord({ ...LED, loginExpired: 'needs login - Please run /login' })).toEqual({ text: 'needs login', tone: 'info' });
    });
    test('a null login paints the row exactly as before', () => {
        expect(stateWord(LED).text).toBe(stateWord({ ...LED, loginExpired: null }).text);
        expect(stateWord(LED).text).not.toBe('needs login');
    });
});
