import { describe, expect, it } from 'vitest';
import { liveFromRows, openConversation, type ConversationOpenHost, type LiveSession } from './open';

function fakeHost(live: LiveSession | null, switched = true) {
    const log = { switched: [] as LiveSession[], hashes: [] as string[] };
    const host: ConversationOpenHost = {
        liveSessionFor: async () => live,
        switchTo: async (s) => {
            log.switched.push(s);
            return switched;
        },
        showHash: (h) => {
            log.hashes.push(h);
        },
    };
    return { host, log };
}

describe('liveFromRows', () => {
    const rows = [
        { session: { id: 'ses_dead', claude_session_uuid: 'conv-1' }, tmux_session: 'cloude_dead', activity_status: 'dead' },
        { claude_session_uuid: 'conv-1', session: { id: 'remote:peer-ab:cloude_w' }, tmux_session: 'cloude_w', activity_status: 'idle' },
        { session: { id: 'ses_nested', claude_session_uuid: 'conv-1' }, tmux_session: 'cloude_live', activity_status: 'idle' },
    ];

    it('finds the live row by the wrapper-level conversation id (a paired computer\'s row too), skipping a dead one', () => {
        expect(liveFromRows(rows, 'conv-1')).toEqual({ sessionId: 'remote:peer-ab:cloude_w', tmuxName: 'cloude_w' });
    });

    it('answers null when no row carries the conversation', () => {
        expect(liveFromRows(rows, 'conv-2')).toBeNull();
        expect(liveFromRows([null, 'x', 3], 'conv-1')).toBeNull();
    });
});

describe('openConversation', () => {
    it('switches to the live session on the conversation', async () => {
        const { host, log } = fakeHost({ sessionId: 'ses_a', tmuxName: 'cloude_a' });
        const outcome = await openConversation({ conversationId: 'c', sessionUuid: 'u', projectId: 7 }, host);
        expect(outcome).toBe('switched');
        expect(log.switched).toEqual([{ sessionId: 'ses_a', tmuxName: 'cloude_a' }]);
        expect(log.hashes).toEqual([]);
    });

    it('a switch that does not land is failed, never a silent page jump', async () => {
        const { host, log } = fakeHost({ sessionId: 'ses_a', tmuxName: 'cloude_a' }, false);
        expect(await openConversation({ conversationId: 'c', sessionUuid: 'u', projectId: 7 }, host)).toBe('failed');
        expect(log.hashes).toEqual([]);
    });

    it('with no live session, opens the saved session on the sessions page to resume it', async () => {
        const { host, log } = fakeHost(null);
        expect(await openConversation({ conversationId: 'c', sessionUuid: 'uuid-9', projectId: 7 }, host)).toBe('page');
        expect(log.hashes).toEqual(['#sessions/uuid-9']);
    });

    it('a conversation that never had a Carnivore session opens nothing', async () => {
        const { host, log } = fakeHost(null);
        expect(await openConversation({ conversationId: 'c', sessionUuid: null, projectId: null }, host)).toBe('none');
        expect(log.hashes).toEqual([]);
        expect(log.switched).toEqual([]);
    });
});
