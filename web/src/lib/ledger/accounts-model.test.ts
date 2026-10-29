import { describe, expect, test } from 'vitest';

import { createI18n } from '../../../../client/js/i18n/runtime.js';
import {
    accountBody,
    draftRefusal,
    storedAccountBody,
    pathDefaultFor,
    pathFieldFor,
    pathHelpKey,
    pathLabelKey,
    refusalText,
    slugFromName,
} from './accounts-model';
import { LEDGER_KEYS } from './ledger-model';

const i18n = createI18n({ locale: 'en' }) as {
    t(key: string, params?: Record<string, unknown> | null): string;
};
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

const SERVER_ID_SHAPE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

describe('the id derived from a name', () => {
    test('a plain two word name becomes a dashed slug', () => {
        expect(slugFromName('work max')).toBe('work-max');
    });

    test('capitals are folded down, because the server refuses them', () => {
        expect(slugFromName('Work Max')).toBe('work-max');
    });

    test('punctuation and runs of spaces collapse to ONE dash, never two', () => {
        expect(slugFromName('  Alex!!  personal  ')).toBe('alex-personal');
    });

    test('digits survive, so "claude 20x" keeps the thing that tells it apart', () => {
        expect(slugFromName('claude 20x')).toBe('claude-20x');
    });

    test('a name with nothing usable in it derives NOTHING, not a fallback', () => {
        expect(slugFromName('###')).toBe('');
        expect(slugFromName('   ')).toBe('');
    });

    test('every derived id the form will send matches the server shape', () => {
        const names = ['work max', 'Alex!!  personal', 'claude 20x', 'a--b', '-lead-', 'Ünïcode'];
        for (const name of names) {
            const slug = slugFromName(name);
            if (slug === '') continue;
            expect(slug, name).toMatch(SERVER_ID_SHAPE);
        }
    });
});

describe('which path field the provider reads', () => {
    test('a claude account is pointed at a config dir', () => {
        expect(pathFieldFor('claude')).toBe('claude_config_dir');
        expect(pathDefaultFor('claude')).toBe('~/.claude');
        expect(pathLabelKey('claude')).toBe(LEDGER_KEYS.editorClaudeDirLabel);
        expect(pathHelpKey('claude')).toBe(LEDGER_KEYS.editorClaudeDirHelp);
    });

    test('a codex account is pointed at a codex home', () => {
        expect(pathFieldFor('codex')).toBe('codex_home');
        expect(pathDefaultFor('codex')).toBe('~/.codex');
        expect(pathLabelKey('codex')).toBe(LEDGER_KEYS.editorCodexHomeLabel);
        expect(pathHelpKey('codex')).toBe(LEDGER_KEYS.editorCodexHomeHelp);
    });

    test('the two helper sentences are different words, not one reused', () => {
        expect(t(LEDGER_KEYS.editorClaudeDirHelp)).not.toBe(t(LEDGER_KEYS.editorCodexHomeHelp));
    });
});

describe('the body that goes on the wire', () => {
    test('a claude draft carries the typed dir and the default codex home', () => {
        expect(
            accountBody({
                name: 'work max',
                provider: 'claude',
                path: '~/.claude-work',
                managed: false,
                color: null,
            }),
        ).toEqual({
            name: 'work max',
            provider: 'claude',
            claude_config_dir: '~/.claude-work',
            codex_home: '~/.codex',
            managed: false,
            color: null,
        });
    });

    test('a codex draft carries the typed home and the default claude dir', () => {
        expect(
            accountBody({
                name: 'side',
                provider: 'codex',
                path: '~/.codex-side',
                managed: false,
                color: null,
            }),
        ).toEqual({
            name: 'side',
            provider: 'codex',
            claude_config_dir: '~/.claude',
            codex_home: '~/.codex-side',
            managed: false,
            color: null,
        });
    });

    test('the name and the path are trimmed, because a stray space is not a choice', () => {
        const body = accountBody({
            name: '  work  ',
            provider: 'claude',
            path: '  ~/.claude  ',
            managed: false,
            color: null,
        });
        expect(body.name).toBe('work');
        expect(body.claude_config_dir).toBe('~/.claude');
    });

    test('AN ADVANCED BODY CARRIES SIX KEYS AND NO SEVENTH: the server forbids an extra', () => {
        const body = accountBody({
            name: 'work',
            provider: 'claude',
            path: '~/.claude',
            managed: false,
            color: null,
        });
        expect(Object.keys(body).sort()).toEqual([
            'claude_config_dir',
            'codex_home',
            'color',
            'managed',
            'name',
            'provider',
        ]);
    });
});

describe('what the form refuses before it asks the server', () => {
    const ok = {
        name: 'work max',
        provider: 'claude' as const,
        path: '~/.claude',
        managed: false,
        color: null,
    };

    test('a complete draft is not refused', () => {
        expect(draftRefusal(ok, [], t)).toBeNull();
    });

    test('a blank name is refused, and the sentence comes from the catalog', () => {
        expect(draftRefusal({ ...ok, name: '   ' }, [], t)).toBe(t(LEDGER_KEYS.editorNameBlank));
    });

    test('a name that derives no id is refused with its own sentence', () => {
        expect(draftRefusal({ ...ok, name: '###' }, [], t)).toBe(t(LEDGER_KEYS.editorIdBlank));
    });

    test('a blank directory is refused', () => {
        expect(draftRefusal({ ...ok, path: '  ' }, [], t)).toBe(t(LEDGER_KEYS.editorPathBlank));
    });

    test('AN ID ALREADY IN USE IS REFUSED, because the write is an upsert', () => {
        expect(draftRefusal(ok, ['work-max'], t)).toBe(
            t(LEDGER_KEYS.editorIdTaken, { id: 'work-max' }),
        );
    });

    test('COULD NOT READ THE LIST IS NOT NONE TAKEN, so null never refuses', () => {
        expect(draftRefusal(ok, null, t)).toBeNull();
    });
});

describe('the server refusal, turned into a sentence', () => {
    test("a string detail is the server's own words", () => {
        const error = Object.assign(new Error('HTTP 422'), { detail: 'that id is not a slug' });
        expect(refusalText(error, t)).toBe('that id is not a slug');
    });

    test('a validation list names the field and what was wrong with it', () => {
        const error = Object.assign(new Error('HTTP 422'), {
            status: 422,
            detail: [
                { loc: ['body', 'name'], msg: 'name must not be empty', type: 'value_error' },
                { loc: ['path', 'id'], msg: 'id must be a lowercase slug', type: 'value_error' },
            ],
        });
        const text = refusalText(error, t);
        expect(text).toContain(t(LEDGER_KEYS.editorFieldRefusal, {
            field: 'name',
            detail: 'name must not be empty',
        }));
        expect(text).toContain('id must be a lowercase slug');
        expect(text).not.toContain('[object Object]');
    });

    test('the app-wide 400 refusal reads exactly like the route 422 does', () => {
        const error = Object.assign(new Error('HTTP 400'), {
            status: 400,
            detail: [
                {
                    loc: ['body', 'token'],
                    msg: 'Extra inputs are not permitted',
                    type: 'extra_forbidden',
                },
            ],
        });

        expect(refusalText(error, t)).toBe(
            t(LEDGER_KEYS.editorFieldRefusal, {
                field: 'token',
                detail: 'Extra inputs are not permitted',
            }),
        );
    });

    test('a structured detail with a message uses the message', () => {
        const error = Object.assign(new Error('HTTP 500'), { detail: { message: 'config locked' } });
        expect(refusalText(error, t)).toBe('config locked');
    });

    test("no detail at all falls back to the error's own message", () => {
        expect(refusalText(new Error('Failed to fetch'), t)).toBe('Failed to fetch');
    });

    test('something that is not an error at all still reads as text', () => {
        expect(refusalText('nope', t)).toBe('nope');
    });
});

describe('a managed account, which is what adding one means now', () => {
    const managed = {
        name: 'claude one',
        provider: 'claude' as const,
        path: '~/.claude',
        managed: true,
        color: '#a3e635',
    };

    test('THE BODY STATES NO POINTER AT ALL, because the server derives it', () => {
        const body = accountBody(managed);
        expect(body).not.toHaveProperty('claude_config_dir');
        expect(body).not.toHaveProperty('codex_home');
    });

    test('it carries exactly the four keys the managed case declares', () => {
        expect(Object.keys(accountBody(managed)).sort()).toEqual([
            'color',
            'managed',
            'name',
            'provider',
        ]);
    });

    test('managed rides on the wire as true', () => {
        expect(accountBody(managed).managed).toBe(true);
    });

    test('the chosen colour rides along', () => {
        expect(accountBody(managed).color).toBe('#a3e635');
    });

    test('NO COLOUR IS SENT AS null, never omitted and never defaulted', () => {
        const body = accountBody({ ...managed, color: null });
        expect(body.color).toBeNull();
        expect(Object.keys(body)).toContain('color');
    });

    test('A MANAGED DRAFT IS NOT REFUSED FOR A BLANK PATH', () => {
        expect(draftRefusal({ ...managed, path: '   ' }, [], t)).toBeNull();
    });

    test('a managed draft is still refused for a blank name', () => {
        expect(draftRefusal({ ...managed, name: '  ' }, [], t)).toBe(
            t(LEDGER_KEYS.editorNameBlank),
        );
    });

    test('a managed draft is still refused for an id already in use', () => {
        expect(draftRefusal(managed, ['claude-one'], t)).toBe(
            t(LEDGER_KEYS.editorIdTaken, { id: 'claude-one' }),
        );
    });

    test('AN ADVANCED DRAFT IS STILL REFUSED FOR A BLANK PATH', () => {
        expect(draftRefusal({ ...managed, managed: false, path: '  ' }, [], t)).toBe(
            t(LEDGER_KEYS.editorPathBlank),
        );
    });
});

describe('editing a row that is already stored', () => {
    const MANAGED_ROW = {
        id: 'claude-one',
        name: 'claude one',
        provider: 'claude',
        claude_config_dir: '/Users/a/.carnivore/accounts/claude-one',
        codex_home: '~/.codex',
        managed: true,
        color: null,
    };

    const NAMED_ROW = {
        id: 'work',
        name: 'work',
        provider: 'claude',
        claude_config_dir: '~/.claude-work',
        codex_home: '~/.codex-side',
        managed: false,
        color: '#a3e635',
    };

    test('a managed row is written back with its colour and no pointer', () => {
        expect(
            storedAccountBody(MANAGED_ROW, { name: 'claude one', color: '#818cf8' }),
        ).toEqual({
            name: 'claude one',
            provider: 'claude',
            managed: true,
            color: '#818cf8',
        });
    });

    test('AN UNMANAGED ROW KEEPS BOTH POINTERS EXACTLY AS STORED', () => {
        expect(storedAccountBody(NAMED_ROW, { name: 'work', color: '#f472b6' })).toEqual({
            name: 'work',
            provider: 'claude',
            managed: false,
            color: '#f472b6',
            claude_config_dir: '~/.claude-work',
            codex_home: '~/.codex-side',
        });
    });

    test('A NEW NAME REPLACES THE STORED ONE AND CHANGES NOTHING ELSE', () => {
        expect(storedAccountBody(NAMED_ROW, { name: 'day job', color: '#a3e635' })).toEqual({
            name: 'day job',
            provider: 'claude',
            managed: false,
            color: '#a3e635',
            claude_config_dir: '~/.claude-work',
            codex_home: '~/.codex-side',
        });
    });

    test('THE BODY NEVER CARRIES AN id, so a renamed row cannot address a different one', () => {
        const body = storedAccountBody(NAMED_ROW, { name: 'day job', color: null });
        expect(body).not.toBeNull();
        expect(Object.keys(body as object)).not.toContain('id');
    });

    test('a name with space around it is trimmed, because the space is not a choice', () => {
        expect(storedAccountBody(MANAGED_ROW, { name: '  day job  ', color: null })?.name).toBe(
            'day job',
        );
    });

    test('a colour can be taken back off a row', () => {
        const body = storedAccountBody(
            { id: 'work', name: 'work', provider: 'codex', managed: true, color: '#a3e635' },
            { name: 'work', color: null },
        );
        expect(body?.color).toBeNull();
    });

    test('a colour the palette never offered still goes on the wire', () => {
        expect(storedAccountBody(MANAGED_ROW, { name: 'claude one', color: '#123456' })?.color).toBe(
            '#123456',
        );
    });

    test('A BLANK NEW NAME ANSWERS null RATHER THAN WRITING AN EMPTY ONE', () => {
        expect(storedAccountBody(MANAGED_ROW, { name: '   ', color: null })).toBeNull();
    });

    test('A ROW WITH NO USABLE PROVIDER ANSWERS null RATHER THAN INVENTING ONE', () => {
        expect(storedAccountBody({ id: 'work' }, { name: 'work', color: '#a3e635' })).toBeNull();
    });

    test('an unmanaged row missing a stored pointer answers null, never a default', () => {
        expect(
            storedAccountBody(
                { id: 'work', name: 'work', provider: 'claude', managed: false },
                { name: 'work', color: '#a3e635' },
            ),
        ).toBeNull();
    });

    test('MANAGED ABSENT IS READ AS false, which is what the server stores', () => {
        const body = storedAccountBody(
            {
                id: 'work',
                name: 'work',
                provider: 'claude',
                claude_config_dir: '~/.claude-work',
                codex_home: '~/.codex',
            },
            { name: 'work', color: '#a3e635' },
        );
        expect(body?.managed).toBe(false);
    });
});

describe('the refusal shape every hand-raised ledger error takes', () => {
    function refusal(detail: unknown, message = 'HTTP 409'): Error {
        const error = new Error(message) as Error & { detail: unknown };
        error.detail = detail;
        return error;
    }

    test('A STRUCTURED {code, detail} READS ITS OWN SENTENCE, not "HTTP 409"', () => {
        expect(
            refusalText(
                refusal({ code: 'managed_dir_unavailable', detail: 'permission denied' }),
                t,
            ),
        ).toBe('permission denied');
    });

    test('a nested validation list names the field, exactly as a flat one does', () => {
        expect(
            refusalText(
                refusal({
                    code: 'invalid_account',
                    detail: [{ loc: ['name'], msg: 'name must not be empty' }],
                }),
                t,
            ),
        ).toBe(t(LEDGER_KEYS.editorFieldRefusal, { field: 'name', detail: 'name must not be empty' }));
    });

    test('a message beside a detail still wins, so nothing already read changes', () => {
        expect(refusalText(refusal({ message: 'said this', detail: 'not this' }), t)).toBe(
            'said this',
        );
    });

    test("a detail with nothing readable in it falls back to the error's own words", () => {
        expect(refusalText(refusal({ code: 'not_found' }, 'HTTP 404'), t)).toBe('HTTP 404');
    });
});

describe('the short name on an edit', () => {
    const ROW = { id: 'work', name: 'work', provider: 'claude', managed: true, color: null };

    test('absent is not sent, so the server keeps the stored one', () => {
        expect(storedAccountBody(ROW, { name: 'work', color: null })).not.toHaveProperty('short_name');
    });

    test('a typed one is trimmed and an empty one is sent as empty to clear', () => {
        expect(storedAccountBody(ROW, { name: 'work', color: null, short_name: ' w ' })?.short_name).toBe('w');
        expect(storedAccountBody(ROW, { name: 'work', color: null, short_name: '' })?.short_name).toBe('');
    });
});
