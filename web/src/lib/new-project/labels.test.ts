import { describe, expect, test } from 'vitest';

import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { NEW_PROJECT_KEYS, landsLine } from '../../../../client/js/labels/new-project.js';
import enCatalog from '../../../../client/js/i18n/catalog.en.js';

const i18n = createI18n({ locale: 'en' }) as { t(key: string, params?: Record<string, unknown> | null): string };
const t = (key: string, params?: Record<string, unknown> | null): string => i18n.t(key, params);

const SERVER_CODES = ['pick_folder', 'scratch', 'sign_in_folder', 'already_project', 'inside_project', 'outside_org', 'no_company', 'company', 'other_company', 'clean'];
const FORM_CODES = ['new_company', 'name', 'name_missing'];

describe('landsLine', () => {
    test('every code has a sentence, in lowercase and with its parameters filled in', () => {
        const params = { project: 'payroll', company: 'Globex', owner: 'Acme', parent: 'Acme', name: 'x' };
        for (const code of [...SERVER_CODES, ...FORM_CODES]) {
            const line = landsLine({ level: 'warn', code, params }, t);
            expect(line.text, code).not.toBe(code);
            expect(line.text, code).not.toMatch(/\{\w+\}/);
        }
    });

    test('a level is a small leading word, and a block says stop', () => {
        expect(landsLine({ level: 'ok', code: 'clean', params: {} }, t).word).toBe('ok');
        expect(landsLine({ level: 'warn', code: 'outside_org', params: {} }, t).word).toBe('warn');
        expect(landsLine({ level: 'block', code: 'scratch', params: {} }, t).word).toBe('stop');
    });

    test('an unknown code shows the code, never nothing', () => {
        expect(landsLine({ level: 'warn', code: 'from_a_newer_server', params: {} }, t).text).toBe('from_a_newer_server');
    });
});

describe('the catalog', () => {
    test('every key the form names exists, and none is shouted', () => {
        const cat = enCatalog as Record<string, string>;
        for (const key of Object.values(NEW_PROJECT_KEYS)) {
            expect(cat[key], key).toBeTypeOf('string');
            expect(cat[key], key).toBe(cat[key]!.toLowerCase());
        }
    });
});
