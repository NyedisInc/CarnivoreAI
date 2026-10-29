import { describe, expect, it } from 'vitest';
import { STATUS_STATES } from '../../cplugs/huddle/swarm/characters/states';
import { memberOf, memberState } from './member-face';

describe('memberState: the light signals as the character state', () => {
    it('each of the eight status states draws its own state', () => {
        for (const status of STATUS_STATES) {
            expect(memberState({ status }).state, status).toBe(status);
        }
    });

    it('unread at rest is the finished-turn glow; unread on a working agent stays working, as the light does', () => {
        expect(memberState({ status: 'idle', unread: true })).toEqual({ state: 'finished_unread', unread: false });
        expect(memberState({ status: 'working', unread: true }).state).toBe('working');
        expect(memberState({ status: 'dead', unread: true }).state).toBe('dead');
    });

    it('the startup gate outranks a question, as on the light', () => {
        expect(memberState({ status: 'question', startupGate: 'awaiting_startup_prompt' }).state).toBe('startup_gate');
    });

    it('asleep keeps its own state; an unread moon raises the flag ring', () => {
        expect(memberState({ status: 'asleep' })).toEqual({ state: 'asleep', unread: false });
        expect(memberState({ status: 'asleep', unread: true })).toEqual({ state: 'asleep', unread: true });
    });

    it('a lost socket or an unreachable computer is never a confident state, and never dead', () => {
        expect(memberState({ status: 'working', transport: 'disconnected' }).state).toBe('unknown');
        expect(memberState({ status: 'idle', hostOffline: 'studio' }).state).toBe('unknown');
        expect(memberState({ status: null }).state).toBe('unknown');
        expect(memberState({ status: 'typing' }).state).toBe('unknown');
    });

    it('over the usage limit is the alarm', () => {
        expect(memberState({ status: 'working', usageLimit: 'over limit' }).state).toBe('alert_immediate');
    });
});

describe('memberOf: who is a member', () => {
    const roster = [
        { id: 4, rank: 'project', session_uuid: 'u-lead', character_seed: 99 },
        { id: 9, rank: 'feature', session_uuid: 'u-gone', state: 'torn_down' },
    ];

    it('the wrapper fields win', () => {
        expect(memberOf({ session_uuid: 'x', swarm_agent_id: 7, swarm_rank: 'feature', swarm_character_seed: 3 }, roster)).toEqual({ agentId: 7, rank: 'feature', seed: 3 });
    });

    it('with no wrapper fields the roster agent whose body is the session is matched by uuid', () => {
        expect(memberOf({ session_uuid: 'u-lead' }, roster)).toEqual({ agentId: 4, rank: 'project', seed: 99 });
        expect(memberOf({ session: { session_uuid: 'u-lead' } }, roster)?.agentId).toBe(4);
    });

    it('a plain session, or one whose agent was torn down, is no member', () => {
        expect(memberOf({ session_uuid: 'u-plain' }, roster)).toBeNull();
        expect(memberOf({ session_uuid: 'u-gone' }, roster)).toBeNull();
        expect(memberOf({}, roster)).toBeNull();
    });
});
