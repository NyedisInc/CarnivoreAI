import { describe, expect, test } from 'vitest';

import { groupSessionsByAccount, sessionTitle, type ProviderSession } from './ledger-sessions';

const row = (id: string, account_id: string | null | undefined, label: string | null = null): ProviderSession => ({
    session: { id } as ProviderSession['session'],
    tmux_session: `tmux_${id}`,
    label,
    account_id,
});

describe('groupSessionsByAccount', () => {
    test('groups by account id, keeps listing order, gives every known account a list', () => {
        const rows = [row('1', 'a'), row('2', 'b'), row('3', 'a')];
        const out = groupSessionsByAccount(rows, ['a', 'b', 'c']);
        expect(out.byAccount.get('a')?.map((r) => r.session.id)).toEqual(['1', '3']);
        expect(out.byAccount.get('b')?.map((r) => r.session.id)).toEqual(['2']);
        expect(out.byAccount.get('c')).toEqual([]);
        expect(out.unknown).toEqual([]);
    });

    test('null, absent and unlisted account ids go to unknown', () => {
        const rows = [row('1', null), row('2', undefined), row('3', 'ghost'), row('4', 'a')];
        const out = groupSessionsByAccount(rows, ['a']);
        expect(out.unknown.map((r) => r.session.id)).toEqual(['1', '2', '3']);
        expect(out.byAccount.get('a')?.length).toBe(1);
    });

    test('matches the id, never a display name', () => {
        const rows = [row('1', 'Work')];
        expect(groupSessionsByAccount(rows, ['work']).unknown.length).toBe(1);
    });

    test('no rows gives empty lists', () => {
        const out = groupSessionsByAccount([], ['a']);
        expect(out.byAccount.get('a')).toEqual([]);
        expect(out.unknown).toEqual([]);
    });
});

describe('sessionTitle', () => {
    test('label, then tmux name, then id', () => {
        expect(sessionTitle(row('1', 'a', 'my task'))).toBe('my task');
        expect(sessionTitle(row('1', 'a'))).toBe('tmux_1');
        expect(sessionTitle({ session: { id: 's' } as ProviderSession['session'], tmux_session: null, label: null })).toBe('s');
    });
});
