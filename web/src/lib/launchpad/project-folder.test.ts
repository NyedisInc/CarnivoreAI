import { describe, expect, test } from 'vitest';

import { createI18n } from '../../../../client/js/i18n/runtime.js';
import {
    PROJECT_CREATE_KEYS,
    nameRefusal,
} from '../../../../client/js/labels/project-create.js';
import { ILLEGAL_CHARS, MAX_NAME_BYTES, validateName } from './project-folder';

function enT(): (key: string, params?: Record<string, unknown> | null) => string {
    const i18n = createI18n({ locale: 'en' }) as {
        t(key: string, params?: Record<string, unknown> | null): string;
    };
    return (key, params) => i18n.t(key, params);
}

describe('RULE: a project name is REFUSED, never rewritten', () => {
    test('a name with spaces is accepted and used exactly as typed', () => {
        const verdict = validateName('Punchlist Test');
        expect(verdict.ok).toBe(true);
        expect(verdict.code).toBe(null);
    });

    test('ordinary names are accepted', () => {
        for (const name of ['api', 'my-app', 'my_app', 'App 2', 'v1.2', 'a']) {
            expect(validateName(name).ok, name).toBe(true);
        }
    });

    test('a forward slash is refused by name, and the name is unchanged', () => {
        const verdict = validateName('a/b');
        expect(verdict.ok).toBe(false);
        expect(verdict.code).toBe('illegal_char');
        expect(verdict.params.char).toBe('/');
        expect(Object.values(verdict.params)).not.toContain('a-b');
    });

    test('the refusal is a sentence a user can act on', () => {
        const t = enT();
        expect(nameRefusal(validateName('a/b'), t)).toBe("a project name cannot contain '/'");
        expect(nameRefusal(validateName(''), t)).toBe('a project name is required');
        expect(nameRefusal(validateName('.hidden'), t)).toBe(
            'a project name cannot start with a dot',
        );
        expect(nameRefusal(validateName('..'), t)).toBe("a project name cannot be '.' or '..'");
        expect(nameRefusal(validateName('bad\nname'), t)).toBe(
            'a project name cannot contain control characters',
        );
        expect(nameRefusal(validateName('x'.repeat(MAX_NAME_BYTES + 1)), t)).toBe(
            'a project name cannot be longer than 255 bytes',
        );
        expect(nameRefusal(validateName('api'), t)).toBe(null);
    });

    test('a backslash is refused', () => {
        expect(validateName('back\\slash').ok).toBe(false);
        expect(validateName('back\\slash').params.char).toBe('\\');
    });

    test('a null byte is refused and named as one, not as a character', () => {
        const verdict = validateName(`a${String.fromCharCode(0)}b`);
        expect(verdict.ok).toBe(false);
        expect(verdict.code).toBe('illegal_null');
        expect(nameRefusal(verdict, enT())).toBe('a project name cannot contain a null character');
    });

    test('dot, dot-dot and a traversal segment are refused', () => {
        expect(validateName('.').code).toBe('reserved');
        expect(validateName('..').code).toBe('reserved');
        expect(validateName('../escape').ok).toBe(false);
    });

    test('a leading dot is refused so the project is not invisible', () => {
        expect(validateName('.hidden').code).toBe('leading_dot');
    });

    test('control characters are refused', () => {
        expect(validateName('bad\nname').code).toBe('control_chars');
        expect(validateName('bad\tname').code).toBe('control_chars');
        expect(validateName(`bad${String.fromCharCode(127)}name`).code).toBe('control_chars');
    });

    test('an empty or whitespace-only name is refused', () => {
        expect(validateName('').code).toBe('required');
        expect(validateName('   ').code).toBe('required');
        expect(validateName(null).code).toBe('required');
        expect(validateName(undefined).code).toBe('required');
    });

    test('the length limit is counted in bytes, not characters', () => {
        expect(validateName('x'.repeat(MAX_NAME_BYTES)).ok).toBe(true);
        expect(validateName('x'.repeat(MAX_NAME_BYTES + 1)).ok).toBe(false);
        expect(validateName('\u{1F600}'.repeat(64)).ok).toBe(false);
    });

    test('a space is NOT on the illegal list, and the other three are', () => {
        expect(ILLEGAL_CHARS).toContain('/');
        expect(ILLEGAL_CHARS).toContain('\\');
        expect(ILLEGAL_CHARS).toContain(String.fromCharCode(0));
        expect(ILLEGAL_CHARS as readonly string[]).not.toContain(' ');
    });

    test('NEGATIVE CONTROL: the checker does not refuse everything', () => {
        const accepted = ['api', 'Punchlist Test', 'v1.2', 'a b c'].filter(
            (n) => validateName(n).ok,
        );
        expect(accepted).toHaveLength(4);
    });

    test('every refusal renders a lowercase sentence with no dashes', () => {
        const t = enT();
        const refusals = ['', 'a/b', '.', '.hidden', 'bad\nname', 'x'.repeat(300)]
            .map((n) => nameRefusal(validateName(n), t))
            .filter((s): s is string => typeof s === 'string');
        expect(refusals).toHaveLength(6);
        for (const sentence of refusals) {
            expect(sentence, sentence).not.toMatch(/^[A-Z]/);
            expect(sentence, sentence).not.toMatch(/[–—]/);
        }
    });

    test('every refusal code has a key, and the keys exist in the catalog', () => {
        const t = enT();
        const codes = [
            'required',
            'illegal_char',
            'illegal_null',
            'control_chars',
            'reserved',
            'leading_dot',
            'too_long',
        ];
        for (const code of codes) {
            const sentence = nameRefusal({ ok: false, code, params: { char: '/', max: 255 } }, t);
            expect(sentence, code).not.toMatch(/^project\./);
        }
        expect(Object.keys(PROJECT_CREATE_KEYS).length).toBeGreaterThan(40);
    });
});
