import { beforeEach, describe, expect, it } from 'vitest';
import * as M from './group-membership';
import { EMPTY_CONTEXT, ruleOf } from './group-rule';

const row = (name: string, extra: Record<string, unknown> = {}) => ({ name, session_uuid: `u-${name}`, kind: 'agent', ...extra });

beforeEach(() => {
    M.clear();
    M.setRuleContext(EMPTY_CONTEXT);
});

describe('group rule membership', () => {
    it('needs EVERY lit criterion, and a prefix or suffix narrows by the shown name', () => {
        const rule = ruleOf({ flags: ['sleeping', 'sharing'], prefix: 'API', suffix: '-x' });
        M.rebuild([{ group_uuid: 'g1', rule }]);
        M.setIdentities([
            row('api-a-x', { asleep: true, spectator_expires_at: '2030-01-01' }),
            row('api-b-x', { asleep: true }),
            row('api-c', { asleep: true, spectator_expires_at: '2030-01-01' }),
            row('web-d-x', { asleep: true, spectator_expires_at: '2030-01-01' }),
        ]);
        expect(['api-a-x', 'api-b-x', 'api-c', 'web-d-x'].map(M.groupOf)).toEqual(['g1', null, null, null]);
        expect(M.countMatching(rule!)).toBe(1);
    });

    it('reads coffee from the live context and running as awake', () => {
        M.rebuild([{ group_uuid: 'g1', rule: ruleOf({ flags: ['running', 'coffee'] }) }]);
        M.setRuleContext({ ...EMPTY_CONTEXT, keptAwake: (n) => n === 'a' });
        M.setIdentities([row('a'), row('b'), row('c', { asleep: true })]);
        expect([M.groupOf('a'), M.groupOf('b'), M.groupOf('c')]).toEqual(['g1', null, null]);
    });

    it('keeps a hand-picked member in its own group even when another rule matches it', () => {
        M.rebuild([
            { group_uuid: 'g1', rule: ruleOf({ flags: ['running'] }) },
            { group_uuid: 'g2', member_session_uuids: ['u-a'], members: ['a'] },
        ]);
        M.setIdentities([row('a'), row('b')]);
        expect([M.groupOf('a'), M.groupOf('b')]).toEqual(['g2', 'g1']);
    });

    it('a group with no rule changes nothing and an empty rule is no rule', () => {
        expect(ruleOf({ flags: [], prefix: '', suffix: '' })).toBeNull();
        M.rebuild([{ group_uuid: 'g1', members: ['a'], member_session_uuids: ['u-a'] }]);
        M.setIdentities([row('a'), row('b')]);
        expect([M.groupOf('a'), M.groupOf('b')]).toEqual(['g1', null]);
    });
});
