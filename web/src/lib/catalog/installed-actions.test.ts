import { describe, expect, test } from 'vitest';

import { createI18n } from '../../../../client/js/i18n/runtime.js';
import {
    canWrite,
    consentTextOf,
    ledgerFailure,
    offersAutoUpdate,
    revisionOf,
    uninstallTargetLines,
} from './installed-actions';

const i18n = createI18n({ locale: 'en' }) as {
    t(key: string, params?: Record<string, unknown> | null): string;
};
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

function apiError(status: number, body: Record<string, unknown> | null = null): Error {
    const error = new Error(`HTTP ${status}`) as Error & {
        status: number;
        body: Record<string, unknown> | null;
    };
    error.status = status;
    error.body = body;
    return error;
}

describe('the revision a write expects', () => {
    test('a recorded number is read exactly', () => {
        expect(revisionOf({ revision: 7 })).toBe(7);
        expect(revisionOf({ revision: 0 })).toBe(0);
    });

    test('anything that is not a finite number is null, never guessed', () => {
        expect(revisionOf({ revision: '7' as never })).toBeNull();
        expect(revisionOf({ revision: Number.NaN })).toBeNull();
        expect(revisionOf({})).toBeNull();
        expect(revisionOf(null)).toBeNull();
    });

    test('a row with no revision CANNOT be written to', () => {
        expect(canWrite({ install_id: 'i1' })).toBe(false);
        expect(canWrite({ revision: 1 })).toBe(false);
        expect(canWrite({ install_id: '  ', revision: 1 })).toBe(false);
        expect(canWrite({ install_id: 'i1', revision: 1 })).toBe(true);
    });
});

describe('the auto-update switch', () => {
    test('it is offered on a writable GLOBAL copy and nowhere else', () => {
        expect(offersAutoUpdate({ install_id: 'i', revision: 1, scope: 'global' })).toBe(true);
        expect(offersAutoUpdate({ install_id: 'i', revision: 1, scope: 'project' })).toBe(false);
    });

    test('an UNKNOWN scope is not a global one', () => {
        expect(offersAutoUpdate({ install_id: 'i', revision: 1 })).toBe(false);
        expect(offersAutoUpdate(null)).toBe(false);
    });
});

describe('reading a rejected write', () => {
    test('404 and 405 are UNSUPPORTED: the route does not exist here', () => {
        expect(ledgerFailure(apiError(404))).toEqual({ kind: 'unsupported' });
        expect(ledgerFailure(apiError(405))).toEqual({ kind: 'unsupported' });
    });

    test('a 500 is NOT unsupported: a server that broke is not one that is old', () => {
        expect(ledgerFailure(apiError(500))).toEqual({ kind: 'failed' });
    });

    test('THE ORDER: a 404 carrying a code is still unsupported', () => {
        expect(ledgerFailure(apiError(404, { code: 'version_revoked' }))).toEqual({
            kind: 'unsupported',
        });
    });

    test('`stale_revision` is a STALE, and it carries the current row out', () => {
        const outcome = ledgerFailure(
            apiError(409, { code: 'stale_revision', row: { install_id: 'i1', revision: 9 } }),
        );
        expect(outcome).toEqual({ kind: 'stale', row: { install_id: 'i1', revision: 9 } });
    });

    test('a stale body that carries the row FLAT is read the same way', () => {
        const outcome = ledgerFailure(
            apiError(409, { code: 'stale_revision', install_id: 'i1', revision: 9 }),
        );
        expect(outcome.kind).toBe('stale');
        expect((outcome as { row: { revision: number } }).row.revision).toBe(9);
    });

    test('a stale body with NO row answers null rather than a made-up one', () => {
        expect(ledgerFailure(apiError(409, { code: 'stale_revision' }))).toEqual({
            kind: 'stale',
            row: null,
        });
    });

    test('any other named code is a REFUSAL carrying that code', () => {
        expect(ledgerFailure(apiError(409, { code: 'scope_shadowed' }))).toEqual({
            kind: 'refused',
            code: 'scope_shadowed',
        });
    });

    test('a code this build has never heard of is STILL a refusal, never swallowed', () => {
        expect(ledgerFailure(apiError(409, { code: 'brand_new_code' }))).toEqual({
            kind: 'refused',
            code: 'brand_new_code',
        });
    });

    test('a rejection with no code and no status is a request that got no answer', () => {
        expect(ledgerFailure(new Error('network down'))).toEqual({ kind: 'failed' });
        expect(ledgerFailure(null)).toEqual({ kind: 'failed' });
    });
});

describe('the folders an uninstall names', () => {
    test('claude and codex each get their own wording', () => {
        expect(
            uninstallTargetLines(
                {
                    targets: [
                        { harness: 'claude', path: '/a/.claude/skills/x' },
                        { harness: 'codex', path: '/a/.codex/skills/x' },
                    ],
                },
                t,
            ),
        ).toEqual(['claude, at /a/.claude/skills/x', 'codex, at /a/.codex/skills/x']);
    });

    test('a harness this build has never heard of is printed, not dropped', () => {
        const said = uninstallTargetLines({ targets: [{ harness: 'zed', path: '/a/b' }] }, t);
        expect(said).toHaveLength(1);
        expect(said[0]).toContain('zed');
        expect(said[0]).toContain('/a/b');
    });

    test('a target with no path is skipped: an empty path says nothing true', () => {
        expect(uninstallTargetLines({ targets: [{ harness: 'claude', path: '  ' }] }, t)).toEqual(
            [],
        );
    });

    test('a ledger row carrying no targets answers EMPTY, not "nowhere"', () => {
        expect(uninstallTargetLines({}, t)).toEqual([]);
        expect(uninstallTargetLines(null, t)).toEqual([]);
    });
});

function wire(detail: Record<string, unknown>): { status: number; body: { detail: Record<string, unknown> } } {
    return { status: 409, body: { detail } };
}

describe('what an update needs consent for', () => {
    test('every member comes off the 409 that asked for it', () => {
        expect(
            consentTextOf(wire({
                code: 'consent_required',
                body: '# new',
                body_sha: 'ab12',
                digest: 'cd34',
                script_files: ['scripts/run.sh'],
            })),
        ).toEqual({
            body: '# new',
            sha: 'ab12',
            digest: 'cd34',
            scripts: ['scripts/run.sh'],
            diff: null,
            requiresConsent: false,
            cplugFacts: null,
        });
    });

    test('DEFECT 1: the real {detail: ...} wrapper is unwrapped, and a flat body still reads', () => {
        const read = consentTextOf(wire({ body: '# real', body_sha: 'sha-real', digest: 'dg-real' }));
        expect([read.body, read.sha, read.digest]).toEqual(['# real', 'sha-real', 'dg-real']);
        expect(consentTextOf({ body: { body: '# flat', body_sha: 'sha-flat' } }).sha).toBe('sha-flat');
    });

    test('requires_consent and the cplug facts are read off the same sheet', () => {
        const facts = { id: 'a/b', name: 'b', permissions: [] };
        const read = consentTextOf(wire({ requires_consent: true, cplug_facts: facts }));
        expect(read.requiresConsent).toBe(true);
        expect(read.cplugFacts).toEqual(facts);
        expect(consentTextOf(wire({ requires_consent: 'yes', cplug_facts: 'x' }))).toMatchObject({
            requiresConsent: false,
            cplugFacts: null,
        });
    });

    test('they are INDEPENDENT: a server may name one and not the others', () => {
        expect(consentTextOf(wire({ body: '# new' }))).toEqual({
            body: '# new',
            sha: null,
            digest: null,
            scripts: [],
            diff: null,
            requiresConsent: false,
            cplugFacts: null,
        });
        expect(consentTextOf(wire({ body_sha: 'ab12' }))).toEqual({
            body: null,
            sha: 'ab12',
            digest: null,
            scripts: [],
            diff: null,
            requiresConsent: false,
            cplugFacts: null,
        });
        expect(consentTextOf(wire({ digest: 'cd34' }))).toEqual({
            body: null,
            sha: null,
            digest: 'cd34',
            scripts: [],
            diff: null,
            requiresConsent: false,
            cplugFacts: null,
        });
    });

    test('a sha or a digest of whitespace is neither, and nothing is computed here', () => {
        expect(consentTextOf(wire({ body_sha: '   ' })).sha).toBeNull();
        expect(consentTextOf(wire({ digest: '  ' })).digest).toBeNull();
        expect(consentTextOf(null)).toEqual({
            body: null,
            sha: null,
            digest: null,
            scripts: [],
            diff: null,
            requiresConsent: false,
            cplugFacts: null,
        });
        expect(consentTextOf(wire({ body: 42, body_sha: 7, digest: 9 }))).toEqual({
            body: null,
            sha: null,
            digest: null,
            scripts: [],
            diff: null,
            requiresConsent: false,
            cplugFacts: null,
        });
    });

    test('a script list is read as PATHS, and an unreadable entry is dropped', () => {
        expect(
            consentTextOf(wire({ script_files: ['scripts/a', 42, '  ', 'bin/b'] })).scripts,
        ).toEqual(['scripts/a', 'bin/b']);
        expect(consentTextOf(wire({ script_files: 'scripts/a' })).scripts).toEqual([]);
    });
});
