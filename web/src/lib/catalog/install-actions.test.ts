import { describe, expect, test } from 'vitest';

import {
    IDLE,
    installedState,
    isBusy,
    refusalCodeOf,
    seededState,
    transition,
    type InstallState,
} from './install-actions';

const EVERY_EVENT = [
    { kind: 'verify' },
    { kind: 'install' },
    { kind: 'installed' },
    { kind: 'update_found' },
    { kind: 'uninstalled' },
    { kind: 'dismiss' },
] as const;

describe('the happy path, one event at a time', () => {
    test('idle -> verifying -> installing -> installed -> update-available', () => {
        let state: InstallState = IDLE;
        state = transition(state, { kind: 'verify' });
        expect(state.kind).toBe('verifying');
        state = transition(state, { kind: 'install' });
        expect(state.kind).toBe('installing');
        state = transition(state, { kind: 'installed' });
        expect(state.kind).toBe('installed');
        state = transition(state, { kind: 'update_found' });
        expect(state.kind).toBe('update-available');
    });

    test('an update runs the same path again and lands installed', () => {
        let state: InstallState = { kind: 'update-available' };
        state = transition(state, { kind: 'verify' });
        expect(state.kind).toBe('verifying');
        state = transition(state, { kind: 'install' });
        state = transition(state, { kind: 'installed' });
        expect(state.kind).toBe('installed');
    });

    test('uninstalling returns an installed row to idle', () => {
        expect(transition({ kind: 'installed' }, { kind: 'uninstalled' }).kind).toBe('idle');
        expect(transition({ kind: 'update-available' }, { kind: 'uninstalled' }).kind).toBe('idle');
    });
});

describe('an install only starts from a verification', () => {
    test('`install` from idle does nothing at all', () => {
        const state = IDLE;
        expect(transition(state, { kind: 'install' })).toBe(state);
    });

    test('and `installed` from anything but installing does nothing', () => {
        expect(transition(IDLE, { kind: 'installed' }).kind).toBe('idle');
        expect(transition({ kind: 'verifying' }, { kind: 'installed' }).kind).toBe('verifying');
    });

    test('a second click while busy does not start a second run', () => {
        const verifying: InstallState = { kind: 'verifying' };
        expect(transition(verifying, { kind: 'verify' })).toBe(verifying);
        const installing: InstallState = { kind: 'installing' };
        expect(transition(installing, { kind: 'verify' })).toBe(installing);
        expect(isBusy(verifying)).toBe(true);
        expect(isBusy(installing)).toBe(true);
        expect(isBusy(IDLE)).toBe(false);
    });

    test('an update badge is only ever raised on an INSTALLED row', () => {
        expect(transition(IDLE, { kind: 'update_found' }).kind).toBe('idle');
        expect(transition({ kind: 'installing' }, { kind: 'update_found' }).kind).toBe('installing');
    });
});

describe('a refusal wins from anywhere and is recorded with its code', () => {
    test('from every state, including the busy ones', () => {
        const states: InstallState[] = [
            IDLE,
            { kind: 'verifying' },
            { kind: 'installing' },
            { kind: 'installed' },
            { kind: 'update-available' },
        ];
        for (const state of states) {
            const next = transition(state, { kind: 'refused', code: 'digest_mismatch' });
            expect(next.kind, state.kind).toBe('refused');
            expect(next.kind === 'refused' && next.code).toBe('digest_mismatch');
        }
    });

    test('a later refusal replaces the code, it does not stack', () => {
        const first = transition(IDLE, { kind: 'refused', code: 'key_untrusted' });
        const second = transition(first, { kind: 'refused', code: 'version_revoked' });
        expect(second.kind === 'refused' && second.code).toBe('version_revoked');
    });
});

describe('refused NEVER collapses into another state', () => {
    const refused: InstallState = { kind: 'refused', code: 'version_revoked' };

    test('no event but a human act moves it', () => {
        for (const event of EVERY_EVENT) {
            if (event.kind === 'verify' || event.kind === 'dismiss') continue;
            expect(transition(refused, event), event.kind).toBe(refused);
        }
    });

    test('specifically: a late `installed` cannot turn a refusal green', () => {
        const next = transition(refused, { kind: 'installed' });
        expect(next.kind).toBe('refused');
        expect(next.kind === 'refused' && next.code).toBe('version_revoked');
    });

    test('and a poll finding an update cannot clear one either', () => {
        expect(transition(refused, { kind: 'update_found' }).kind).toBe('refused');
    });

    test('trying again is a human act, and it starts a fresh verification', () => {
        expect(transition(refused, { kind: 'verify' }).kind).toBe('verifying');
    });

    test('dismissing is the other human act, and only it returns to idle', () => {
        expect(transition(refused, { kind: 'dismiss' }).kind).toBe('idle');
        expect(transition(IDLE, { kind: 'dismiss' })).toBe(IDLE);
    });
});

describe('a fresh listing does not overwrite what a row is doing', () => {
    test('a refused row keeps its refusal through a re-read', () => {
        const refused: InstallState = { kind: 'refused', code: 'scripts_not_supported' };
        expect(seededState(refused, true, true)).toBe(refused);
        expect(seededState(refused, null, false)).toBe(refused);
    });

    test('a busy row keeps its work, because the listing is stale about it', () => {
        const installing: InstallState = { kind: 'installing' };
        expect(seededState(installing, null, false)).toBe(installing);
        const verifying: InstallState = { kind: 'verifying' };
        expect(seededState(verifying, true, true)).toBe(verifying);
    });

    test('an idle row takes the ledger as it finds it', () => {
        expect(seededState(IDLE, false, true).kind).toBe('installed');
        expect(seededState(IDLE, true, true).kind).toBe('update-available');
        expect(seededState(IDLE, null, false).kind).toBe('idle');
    });

    test('and the badge is read as an EXPLICIT true, never as truthiness', () => {
        expect(installedState(true).kind).toBe('update-available');
        expect(installedState(false).kind).toBe('installed');
        expect(installedState(null).kind).toBe('installed');
        expect(installedState(undefined).kind).toBe('installed');
    });
});

describe('reading the refusal code off a rejected call', () => {
    test('from the parsed body, which is where the server puts it', () => {
        expect(refusalCodeOf({ body: { code: 'name_taken' } })).toBe('name_taken');
    });

    test('from a structured detail, which some routes use instead', () => {
        expect(refusalCodeOf({ detail: { code: 'index_rollback' } })).toBe('index_rollback');
    });

    test('a rejection with no code is null, not a guess', () => {
        expect(refusalCodeOf(new Error('boom'))).toBe(null);
        expect(refusalCodeOf({ detail: 'a sentence' })).toBe(null);
        expect(refusalCodeOf({ body: {} })).toBe(null);
        expect(refusalCodeOf({ body: { code: '   ' } })).toBe(null);
        expect(refusalCodeOf(null)).toBe(null);
        expect(refusalCodeOf('nope')).toBe(null);
    });
});
