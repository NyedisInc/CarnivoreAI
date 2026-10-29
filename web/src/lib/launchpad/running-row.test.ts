import { describe, expect, test } from 'vitest';

import { RUNNING_SESSION_KEYS } from '../../../../client/js/labels/running-session.js';
import {
    offersFork,
    renamePencilView,
    sessionRowId,
    themeCueView,
    wrapperPillView,
} from './running-row';
import { row } from './running-harness';

describe('the rename pencil has three states and is never absent', () => {
    test('a row with a session id is renameable, against that id', () => {
        const view = renamePencilView(row('cloude_api', { session_id: 'ses_1' }));
        expect(view.state).toBe('renameable');
        expect(view.renameKey).toBe('ses_1');
        expect(view.reasonKey).toBe(RUNNING_SESSION_KEYS.renameAction);
    });

    test('A TMUX NAME IS ENOUGH: a row with no session id is still renameable', () => {
        const view = renamePencilView(row('cloude_api', { session_id: null }));
        expect(view.state).toBe('renameable');
        expect(view.renameKey).toBe('cloude_api');
    });

    test('a row with NEITHER handle refuses, and names the precondition', () => {
        const view = renamePencilView(row('', {
            session_id: null, created_by_cloude: true,
        }));
        expect(view.state).toBe('unavailable');
        expect(view.renameKey).toBeNull();
        expect(view.reasonKey).toBe(RUNNING_SESSION_KEYS.renameUnopened);
    });

    test('an EXTERNAL row with no handle names adoption, not opening', () => {
        const view = renamePencilView(row('', {
            session_id: null, created_by_cloude: false,
        }));
        expect(view.state).toBe('unavailable');
        expect(view.reasonKey).toBe(RUNNING_SESSION_KEYS.renameUnadopted);
    });

    test('THE THIRD OUTCOME: null ownership is CANNOT DETERMINE, not external', () => {
        const view = renamePencilView(row('', {
            session_id: null, created_by_cloude: null,
        }));
        expect(view.state).toBe('unknown_owner');
        expect(view.reasonKey).toBe(RUNNING_SESSION_KEYS.renameUnknownOwner);
    });

    test('the two refusals share a class, and it is NOT the live one', () => {
        const live = renamePencilView(row('cloude_api'));
        const refused = renamePencilView(row('', { created_by_cloude: null }));
        expect(live.className).toBe('running-session-rename');
        expect(refused.className).toBe('running-session-rename-unavailable');
        expect(refused.className).not.toBe(live.className);
    });

    test('NEGATIVE CONTROL: every state carries a reason key', () => {
        for (const r of [
            row('cloude_api'),
            row('', { created_by_cloude: true }),
            row('', { created_by_cloude: false }),
            row('', { created_by_cloude: null }),
        ]) {
            expect(renamePencilView(r).reasonKey).toMatch(/^session\.rename\./);
        }
    });
});

describe('the durable row id', () => {
    test('renders the id it was given', () => {
        expect(sessionRowId(row('a', { session_row_id: 7 }))).toBe('7');
    });

    test('renders NOTHING for a row that has none', () => {
        expect(sessionRowId(row('a', { session_row_id: null }))).toBeNull();
        expect(sessionRowId(row('a', { session_row_id: undefined }))).toBeNull();
    });

    test('ZERO IS A ROW ID, not an absence', () => {
        expect(sessionRowId(row('a', { session_row_id: 0 }))).toBe('0');
    });
});

describe('fork is offered on owned rows only', () => {
    test('owned yes, external no, unknown no', () => {
        expect(offersFork(row('a', { created_by_cloude: true }))).toBe(true);
        expect(offersFork(row('a', { created_by_cloude: false }))).toBe(false);
        expect(offersFork(row('a', { created_by_cloude: null }))).toBe(false);
    });
});

describe('the launch-wrapper pill', () => {
    test('a label renders a pill carrying that exact text', () => {
        expect(wrapperPillView('claude (chrome)')).toEqual({ label: 'claude (chrome)' });
    });

    test('a null label renders NO pill at all, and no placeholder', () => {
        expect(wrapperPillView(null)).toBeNull();
        expect(wrapperPillView(undefined)).toBeNull();
    });

    test('blank and whitespace-only labels render nothing', () => {
        expect(wrapperPillView('')).toBeNull();
        expect(wrapperPillView('   ')).toBeNull();
    });

    test('a non-string renders nothing rather than [object Object]', () => {
        expect(wrapperPillView({ toString: () => 'x' } as unknown as string)).toBeNull();
        expect(wrapperPillView(42 as unknown as string)).toBeNull();
    });

    test('the label is trimmed, so padding cannot change the pill', () => {
        expect(wrapperPillView('  claude  ')).toEqual({ label: 'claude' });
    });
});

describe('the per-session theme cue', () => {
    const lookup = (id: string) =>
        id === 'dracula' ? { accent: 'rgb(1, 2, 3)', label: 'Dracula' } : null;

    test('a themed row carries the id, one colour and the manifest name', () => {
        expect(themeCueView('dracula', lookup)).toEqual({
            themeId: 'dracula', accent: 'rgb(1, 2, 3)', name: 'Dracula',
        });
    });

    test('all three not-themed cases render nothing', () => {
        expect(themeCueView(null, lookup)).toBeNull();
        expect(themeCueView('nope', lookup)).toBeNull();
        expect(themeCueView('dracula', () => null)).toBeNull();
    });

    test('the id is reduced to what a stylesheet can select on', () => {
        const cue = themeCueView('dra cula!', () => ({
            accent: 'rgb(0, 0, 0)', label: 'x',
        }));
        expect(cue?.themeId).toBe('dracula');
    });

    test('an id with NOTHING safe in it yields an untinted row', () => {
        expect(themeCueView('!!!', () => ({ accent: 'rgb(0,0,0)', label: 'x' })))
            .toBeNull();
    });

    test('the swatch falls back to the id when the manifest has no name', () => {
        const cue = themeCueView('dracula', () => ({
            accent: 'rgb(1, 2, 3)', label: '',
        }));
        expect(cue?.name).toBe('dracula');
    });
});

