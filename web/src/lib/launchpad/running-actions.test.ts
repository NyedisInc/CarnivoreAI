import { describe, expect, test } from 'vitest';

import { RUNNING_SESSION_KEYS } from '../../../../client/js/labels/running-session.js';
import {
    reasonFrom,
    renameFailureText,
    restartSession,
    runRowAction,
    saveRename,
} from './running-actions';
import { recordingHost, row, testTranslate as t } from './running-harness';

function methods(host: { calls: Array<{ method: string }> }): string[] {
    return host.calls.map((c) => c.method);
}

describe('closing and removing', () => {
    test('a confirmed close on a BOUND session goes through the full teardown', async () => {
        const host = recordingHost();
        await runRowAction(row('cloude_api', { session_id: 'ses_1' }), 'close', host, t);
        expect(methods(host)).toEqual(['confirmAction', 'destroySession', 'refresh']);
    });

    test('a DETACHED session is killed directly, with no adoption', async () => {
        const host = recordingHost();
        await runRowAction(row('cloude_api', { session_id: null }), 'close', host, t);
        expect(methods(host)).toEqual([
            'confirmAction', 'resolveSessionId', 'destroyExternalSession', 'refresh',
        ]);
    });

    test('an id lookup that fails destroys nothing and says so (u141-03)', async () => {
        const host = recordingHost();
        host.resolveSessionId = async () => { throw new Error('listing down'); };
        await runRowAction(row('cloude_api', { session_id: null }), 'close', host, t);
        expect(methods(host)).not.toContain('destroySession');
        expect(methods(host)).not.toContain('destroyExternalSession');
        expect(host.errors).toHaveLength(1);
    });

    test('a live id resolved for a detached row still takes the full teardown', async () => {
        const host = recordingHost({ resolveSessionId: 'ses_9' });
        await runRowAction(row('cloude_api', { session_id: null }), 'close', host, t);
        expect(methods(host)).toContain('destroySession');
        expect(methods(host)).not.toContain('destroyExternalSession');
    });

    test('A DECLINED CONFIRM DESTROYS NOTHING AND REFRESHES NOTHING', async () => {
        const host = recordingHost({ confirm: false });
        await runRowAction(row('cloude_api'), 'close', host, t);
        expect(methods(host)).toEqual(['confirmAction']);
    });

    test('THE CONFIRM NAMES THE SESSION THE WAY THE USER KNOWS IT', async () => {
        const host = recordingHost();
        await runRowAction(
            row('cloude_Media_Compression', { label: 'Media Compression' }),
            'close', host, t,
        );
        const call = host.calls.find((c) => c.method === 'confirmAction');
        expect(call?.args).toEqual(['close', 'Media Compression']);
    });

    test('a session with NO label is named by its STRIPPED handle', async () => {
        const host = recordingHost();
        await runRowAction(row('cloude_fstest', { label: null }), 'close', host, t);
        const call = host.calls.find((c) => c.method === 'confirmAction');
        expect(call?.args).toEqual(['close', 'fstest']);
    });

    // there is nothing

    test('a failure is SHOWN and the list is still refreshed', async () => {
        const host = recordingHost();
        host.destroyExternalSession = async () => { throw new Error('HTTP 500'); };
        await runRowAction(row('cloude_api'), 'close', host, t);
        expect(host.errors).toHaveLength(1);
        expect(host.errors[0]).toContain('HTTP 500');
        expect(methods(host)).toContain('refresh');
    });

    test('a row with no name does nothing at all', async () => {
        const host = recordingHost();
        await runRowAction(row(''), 'close', host, t);
        expect(methods(host)).toEqual([]);
    });
});

describe('restarting', () => {
    test('RESTART ASKS THE PICKER FIRST, and never the generic confirm', async () => {
        const host = recordingHost({ restartChoice: { agentType: 'claude-chrome' } });
        await runRowAction(row('cloude_api'), 'restart', host, t);
        expect(methods(host)).toContain('openRestartPicker');
        expect(methods(host)).not.toContain('confirmAction');
    });

    test('the picker is told the row MEASURED status, not a guess', async () => {
        const host = recordingHost({ restartChoice: {} });
        await restartSession(row('cloude_api', { status: 'dead' }), host, t);
        const call = host.calls.find((c) => c.method === 'openRestartPicker');
        expect(call?.args[2]).toBe('dead');
    });

    test('A DECLINED PICKER STARTS NOTHING AND SAYS NOTHING', async () => {
        const host = recordingHost({ restartChoice: null });
        await restartSession(row('cloude_api'), host, t);
        expect(methods(host)).toEqual(['openRestartPicker']);
        expect(host.errors).toHaveLength(0);
    });

    test('a picker that could not PREDICT says why, and starts nothing', async () => {
        const host = recordingHost({
            restartChoice: null, restartError: 'the pane could not be read',
        });
        await restartSession(row('cloude_api'), host, t);
        expect(methods(host)).not.toContain('respawnSession');
        expect(host.errors[0]).toContain(RUNNING_SESSION_KEYS.respawnUnpredictable);
        expect(host.errors[0]).toContain('the pane could not be read');
    });

    test('FAIL CLOSED: no picker module at all is its OWN sentence', async () => {
        const host = recordingHost({ restartChoice: null, hasRestartPicker: false });
        await restartSession(row('cloude_api'), host, t);
        expect(methods(host)).not.toContain('respawnSession');
        expect(host.errors[0]).toContain(RUNNING_SESSION_KEYS.respawnNoPicker);
    });

    test('THE SERVER OK IS THE VERDICT: a 200 with ok:false is a refusal', async () => {
        const host = recordingHost({
            restartChoice: {},
            respawn: { ok: false, detail: 'it started and exited again' },
        });
        await restartSession(row('cloude_api'), host, t);
        expect(methods(host)).not.toContain('reopenAfterRestart');
        expect(host.errors[0]).toContain('it started and exited again');
        expect(methods(host)).toContain('refresh');
    });

    test('an ok:false carrying no detail still says something', async () => {
        const host = recordingHost({ restartChoice: {}, respawn: { ok: false } });
        await restartSession(row('cloude_api'), host, t);
        expect(host.errors[0]).toContain(RUNNING_SESSION_KEYS.respawnNoReason);
    });

    test('a thrown respawn is reported and the list is refreshed', async () => {
        const host = recordingHost({
            restartChoice: {},
            respawn: () => { throw new Error('network down'); },
        });
        await restartSession(row('cloude_api'), host, t);
        expect(host.errors[0]).toContain('network down');
        expect(methods(host)).toContain('refresh');
    });

    test('A CHOICE THAT DID NOT PERSIST IS SAID OUT LOUD', async () => {
        const host = recordingHost({
            restartChoice: { agentType: 'claude-chrome' },
            respawn: { ok: true, agent_type_persisted: false },
            reopen: { status: 'reopened' },
        });
        await restartSession(row('cloude_api'), host, t);
        expect(host.errors[0]).toContain(RUNNING_SESSION_KEYS.respawnChoiceUnsaved);
        expect(host.errors[0]).toContain('claude-chrome');
    });

    test('ON SUCCESS THE USER GOES BACK INTO THE SESSION, and the list is not reloaded', async () => {
        const host = recordingHost({
            restartChoice: {}, respawn: { ok: true }, reopen: { status: 'reopened' },
        });
        await restartSession(row('cloude_api'), host, t);
        expect(methods(host)).toContain('reopenAfterRestart');
        expect(methods(host)).not.toContain('refresh');
    });

    test('a reopen that did NOT happen says why and reloads the list', async () => {
        const host = recordingHost({
            restartChoice: {}, respawn: { ok: true },
            reopen: { status: 'not_reopened', detail: 'the session id was not returned' },
        });
        await restartSession(row('cloude_api'), host, t);
        expect(host.errors[0]).toBe('the session id was not returned');
        expect(methods(host)).toContain('refresh');
    });

    test('the live-restart confirmation flag is passed through unchanged', async () => {
        // decorative.
        const host = recordingHost({
            restartChoice: { agentType: null, confirmRestartLive: true },
            respawn: { ok: true }, reopen: { status: 'reopened' },
        });
        await restartSession(row('cloude_api'), host, t);
        const call = host.calls.find((c) => c.method === 'respawnSession');
        expect(call?.args).toEqual(['cloude_api', null, true]);
    });

    test('and an UNCONFIRMED live restart passes false, never undefined', async () => {
        const host = recordingHost({
            restartChoice: {}, respawn: { ok: true }, reopen: { status: 'reopened' },
        });
        await restartSession(row('cloude_api'), host, t);
        const call = host.calls.find((c) => c.method === 'respawnSession');
        expect(call?.args[2]).toBe(false);
    });
});

describe('renaming', () => {
    test('a changed label is validated and then stored', async () => {
        const host = recordingHost();
        const outcome = await saveRename('ses_1', 'Media v2', 'Media', host, t);
        expect(outcome.state).toBe('saved');
        expect(methods(host)).toEqual(['validateLabel', 'renameSession', 'refresh']);
    });

    test('UNCHANGED WRITES NOTHING, and the basis is the SEED', async () => {
        const host = recordingHost();
        const outcome = await saveRename('ses_1', 'api', 'api', host, t);
        expect(outcome.state).toBe('unchanged');
        expect(methods(host)).toEqual([]);
    });

    test('an EMPTY box is a cancel, not a write of an empty label', async () => {
        const host = recordingHost();
        expect((await saveRename('ses_1', '   ', 'api', host, t)).state)
            .toBe('unchanged');
        expect(methods(host)).toEqual([]);
    });

    test('THE LABEL RULE IS THE SHARED ONE, and a refusal keeps its reason', async () => {
        const host = recordingHost({
            validateLabel: () => ({ ok: false, reason: 'no control characters' }),
        });
        const outcome = await saveRename('ses_1', 'bad', 'api', host, t);
        expect(outcome).toEqual({ state: 'refused', reason: 'no control characters' });
        expect(methods(host)).not.toContain('renameSession');
    });

    test('a refusal with NO reason still says something', async () => {
        const host = recordingHost({ validateLabel: () => ({ ok: false }) });
        const outcome = await saveRename('ses_1', 'x', 'api', host, t);
        expect(outcome.reason).toBe(RUNNING_SESSION_KEYS.renameRuleUnavailable);
    });

    test('THE VALIDATED VALUE IS WHAT IS STORED, not the raw text', async () => {
        const host = recordingHost({
            validateLabel: (value) => ({ ok: true, value: value.trim() }),
        });
        await saveRename('ses_1', '  Media  ', 'api', host, t);
        const call = host.calls.find((c) => c.method === 'renameSession');
        expect(call?.args).toEqual(['ses_1', 'Media']);
    });

    test('a label with punctuation reaches the server instead of being refused', async () => {
        const host = recordingHost();
        await saveRename('ses_1', 'Refactor spike (round 2)', 'api', host, t);
        const call = host.calls.find((c) => c.method === 'renameSession');
        expect(call?.args[1]).toBe('Refactor spike (round 2)');
    });
});

const httpError = (message: string, status: number): Error => Object.assign(new Error(message), { status });

describe('what a rename failure is called', () => {
    test('digits inside the server sentence or a session name never pick the class (u141-09)', () => {
        expect(renameFailureText(httpError('could not rename session 4091', 500), t)).toBe('could not rename session 4091');
        expect(renameFailureText(httpError('session web400 is busy', 503), t)).toBe('session web400 is busy');
    });

    test('409 means the name is taken', () => {
        expect(renameFailureText(httpError('HTTP 409', 409), t))
            .toBe(RUNNING_SESSION_KEYS.renameFailedInUse);
        expect(renameFailureText(new Error('name already in use'), t))
            .toBe(RUNNING_SESSION_KEYS.renameFailedInUse);
    });

    test('400 means the server refused the value', () => {
        expect(renameFailureText(httpError('HTTP 400', 400), t))
            .toBe(RUNNING_SESSION_KEYS.renameFailedInvalid);
    });

    test('404 means the row is gone', () => {
        expect(renameFailureText(httpError('HTTP 404', 404), t))
            .toBe(RUNNING_SESSION_KEYS.renameFailedMissing);
    });

    test('ANYTHING ELSE KEEPS THE SERVER WORDS, never a flattened "rename failed"', () => {
        expect(renameFailureText(new Error('tmux is not running'), t))
            .toBe('tmux is not running');
    });
});

describe('the reason out of a thrown value', () => {
    test('an Error gives its message', () => {
        expect(reasonFrom(new Error('boom'), t)).toBe('boom');
    });

    test('a bare string gives itself', () => {
        expect(reasonFrom('boom', t)).toBe('boom');
    });

    test('an EMPTY message falls back rather than printing undefined', () => {
        expect(reasonFrom(new Error(''), t))
            .toBe(RUNNING_SESSION_KEYS.serverUnreachable);
        expect(reasonFrom(null, t)).toBe(RUNNING_SESSION_KEYS.serverUnreachable);
        expect(reasonFrom({}, t)).toBe(RUNNING_SESSION_KEYS.serverUnreachable);
    });
});
