import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, test } from 'vitest';

import enCatalog from '../../../../client/js/i18n/catalog.en.js';
import {
    REFUSAL_CODES,
    REVIEW_BLOCKING_KINDS,
    REVIEW_KINDS,
    SKILL_KEYS,
    refusalKey,
    reviewKindKey,
} from '../../../../client/js/labels/skill.js';
import {
    SUBMIT_KEYS,
    SUBMIT_REFUSAL_CODES,
    submitRefusalKey,
} from '../../../../client/js/labels/skill-submit.js';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../..');

const SOURCES = [
    'client/js/labels/skill.js',
    'client/js/labels/skill-submit.js',
    'web/src/lib/catalog/CatalogCard.svelte',
    'web/src/lib/catalog/InstallSheet.svelte',
    'web/src/lib/catalog/InstallPreview.svelte',
    'web/src/lib/catalog/InstallChoices.svelte',
    'web/src/lib/catalog/ConsentScripts.svelte',
    'web/src/lib/catalog/LoadoutMembers.svelte',
    'web/src/lib/catalog/ReviewBlock.svelte',
    'web/src/lib/catalog/CatalogScreen.svelte',
    'web/src/lib/catalog/CatalogToolbar.svelte',
    'web/src/lib/catalog/CatalogRows.svelte',
    'web/src/lib/catalog/CatalogDetail.svelte',
    'web/src/lib/catalog/DetailActions.svelte',
    'web/src/lib/catalog/AutoUpdateSwitch.svelte',
    'web/src/lib/catalog/RatingControl.svelte',
    'web/src/lib/catalog/GradeBlock.svelte',
    'web/src/lib/catalog/InstallCount.svelte',
    'web/src/lib/catalog/ConfirmSheet.svelte',
    'web/src/lib/catalog/OneShotPicker.svelte',
];

const COMPOSED_PREFIXES = new Set([
    'skill.refused.',
    'skill.review.kind.',
    'skill.submit.refused.',
]);

const KEYS = new Set(Object.keys(enCatalog as Record<string, unknown>));

describe('the keys this surface names', () => {
    test('every SUBMIT_KEYS value is a real catalog key', () => {
        const missing = Object.entries(SUBMIT_KEYS as Record<string, string>)
            .filter(([, key]) => !KEYS.has(key))
            .map(([name, key]) => `${name} -> ${key}`);
        expect(missing).toEqual([]);
    });

    test('every SKILL_KEYS value is a real catalog key', () => {
        const missing = Object.entries(SKILL_KEYS as Record<string, string>)
            .filter(([, key]) => !KEYS.has(key))
            .map(([name, key]) => `${name} -> ${key}`);
        expect(missing).toEqual([]);
    });

    test('every `skill.` literal in the source is a real catalog key', () => {
        const missing: string[] = [];
        for (const relative of SOURCES) {
            const src = fs.readFileSync(path.join(ROOT, relative), 'utf8');
            const found = src.match(/'skill\.[a-z0-9_.]+'/g) || [];
            for (const literal of found) {
                const key = literal.slice(1, -1);
                if (COMPOSED_PREFIXES.has(key)) continue;
                if (!KEYS.has(key)) missing.push(`${relative}: ${key}`);
            }
        }
        expect(missing).toEqual([]);
    });

    test('NEGATIVE CONTROL: the check can see a key that is not there', () => {
        expect(KEYS.has('skill.catalog.title')).toBe(true);
        expect(KEYS.has('skill.catalog.does_not_exist')).toBe(false);
    });
});

describe('every refusal code has a sentence of its own', () => {
    test('one catalog message per code the client knows', () => {
        const missing = [...REFUSAL_CODES].filter((code) => !KEYS.has(`skill.refused.${code}`));
        expect(missing).toEqual([]);
    });

    test('the eleven 409 codes and the three transport codes are all there', () => {
        for (const code of [
            'signature_invalid',
            'index_rollback',
            'index_serial_jump',
            'key_untrusted',
            'version_revoked',
            'name_reserved',
            'digest_mismatch',
            'scripts_not_supported',
            'name_taken',
            'scope_shadowed',
            'stale_revision',
            'index_unavailable',
            'tls_verify_failed',
            'index_not_json',
            'unsupported',
            'auto_update_global_only',
            'consent_required',
            'loadout_manifest_invalid',
            'loadout_member_unknown',
        ]) {
            expect(REFUSAL_CODES.has(code), code).toBe(true);
            expect(KEYS.has(`skill.refused.${code}`), code).toBe(true);
        }
    });

    test('every review warning kind has a sentence of its own', () => {
        for (const kind of [
            'network',
            'file_delete',
            'credential_access',
            'shell_exec',
            'obfuscation',
            'privilege',
            'other',
            'prompt_injection',
            'settings_write',
            'description_mismatch',
            'opaque_payload',
            'instructions_write',
        ]) {
            expect(REVIEW_KINDS.has(kind), kind).toBe(true);
            expect(KEYS.has(`skill.review.kind.${kind}`), kind).toBe(true);
        }
    });

    test('THE DRIFT GUARD: every blocking kind is a kind', () => {
        const stray = [...REVIEW_BLOCKING_KINDS].filter((kind) => !REVIEW_KINDS.has(kind));
        expect(stray).toEqual([]);
    });

    test('the five blocking kinds and the seven advisory ones, named', () => {
        for (const kind of [
            'prompt_injection',
            'credential_access',
            'obfuscation',
            'opaque_payload',
            'settings_write',
        ]) {
            expect(REVIEW_BLOCKING_KINDS.has(kind), kind).toBe(true);
        }
        for (const kind of [
            'network',
            'shell_exec',
            'file_delete',
            'privilege',
            'description_mismatch',
            'other',
            'instructions_write',
        ]) {
            expect(REVIEW_BLOCKING_KINDS.has(kind), kind).toBe(false);
        }
    });

    test('every verdict this app can paint has a sentence of its own', () => {
        for (const verdict of ['clean', 'flagged', 'blocked', 'unreadable', 'absent']) {
            expect(KEYS.has(`skill.review.verdict.${verdict}`), verdict).toBe(true);
        }
    });

    test('a kind from a newer index is REPORTED, never swallowed', () => {
        expect(reviewKindKey('a_kind_from_the_future')).toBe('skill.review.kind.unrecognised');
        expect(reviewKindKey('')).toBe('skill.review.kind.unrecognised');
        expect(reviewKindKey(null)).toBe('skill.review.kind.unrecognised');
        expect(reviewKindKey('network')).toBe('skill.review.kind.network');
    });

    test('every submission refusal code has a sentence of its own', () => {
        const missing = [...SUBMIT_REFUSAL_CODES].filter(
            (code) => !KEYS.has(`skill.submit.refused.${code}`),
        );
        expect(missing).toEqual([]);
        expect(KEYS.has('skill.submit.refused.unrecognised')).toBe(true);
        expect(KEYS.has('skill.submit.refused.unknown')).toBe(true);
    });

    test('THE COLLISION GUARD: the two shared codes keep BOTH meanings', () => {
        for (const code of ['name_taken', 'body_too_large']) {
            expect(KEYS.has(`skill.refused.${code}`), code).toBe(true);
            expect(KEYS.has(`skill.submit.refused.${code}`), code).toBe(true);
            expect(submitRefusalKey(code)).toBe(`skill.submit.refused.${code}`);
            expect(refusalKey(code)).toBe(`skill.refused.${code}`);
        }
    });

    test('a code from a newer server is REPORTED, never swallowed', () => {
        expect(refusalKey('something_new_from_the_server')).toBe('skill.refused.unrecognised');
        expect(refusalKey('')).toBe('skill.refused.unknown');
        expect(refusalKey(null)).toBe('skill.refused.unknown');
        expect(refusalKey('version_revoked')).toBe('skill.refused.version_revoked');
    });
});
