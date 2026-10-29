/** @vitest-environment jsdom */
import { beforeEach, describe, expect, test, vi } from 'vitest';

vi.mock('../plugins/session-card-actions', () => ({
    sessionCardMenuItems: () => [],
    runSessionCardAction: vi.fn(async () => true),
}));

import { bench, ctxOf, idsOf } from './row-test-env';

beforeEach(() => {
    bench();
});

describe('join or leave the swarm in place of do not disturb', () => {
    const live = { sessionUuid: 'u-1', sessionId: 'ses_1', agentFamily: 'claude', status: 'idle', owned: true };

    test('a member shows leave the swarm, never join', () => {
        const ids = idsOf(ctxOf({ ...live, swarmRank: 'feature' }));
        expect(ids).toContain('swarm-leave');
        expect(ids).not.toContain('swarm-join');
        expect(ids).toContain('mute');
        expect(ids).not.toContain('huddle-do-not-disturb');
    });

    test('a session outside the swarm shows join the swarm, never leave', () => {
        const ids = idsOf(ctxOf({ ...live, swarmRank: '' }));
        expect(ids).toContain('swarm-join');
        expect(ids).not.toContain('swarm-leave');
        expect(ids).toContain('mute');
        expect(ids).not.toContain('huddle-do-not-disturb');
    });
});
