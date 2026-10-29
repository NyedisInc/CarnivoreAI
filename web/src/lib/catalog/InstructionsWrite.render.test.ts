/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { mount, unmount } from 'svelte';

import CatalogCard from './CatalogCard.svelte';
import TrySheet from './TrySheet.svelte';
import OneShotPicker from './OneShotPicker.svelte';
import LoadoutMembers from './LoadoutMembers.svelte';
import { loadoutFacts } from './loadout-facts';
import { updateSheet } from './installed-actions';
import InstallSheet from './InstallSheet.svelte';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { reviewKindLabel } from '../../../../client/js/labels/skill.js';
import { cardView } from './card';
import type { CatalogHost } from './catalog';
import type { CatalogReview, InstallPreview } from './types';

const i18n = createI18n({ locale: 'en' }) as {
    t(key: string, params?: Record<string, unknown> | null): string;
};
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

const REVIEW: CatalogReview = {
    status: 'reviewed',
    summary: 's',
    verdict: 'flagged',
    warnings: [{ kind: 'instructions_write', detail: 'appends to CLAUDE.md', file: 'SKILL.md' }],
};
const OTHER_REVIEW: CatalogReview = {
    status: 'reviewed',
    summary: 's',
    verdict: 'flagged',
    warnings: [{ kind: 'network', detail: 'fetches', file: 'SKILL.md' }],
};

let mounted: Record<string, unknown> | null = null;

afterEach(() => {
    if (mounted) unmount(mounted as never);
    mounted = null;
    document.body.innerHTML = '';
});

function mountCard(review: CatalogReview): void {
    const target = document.createElement('div');
    document.body.appendChild(target);
    mounted = mount(CatalogCard, {
        target,
        props: {
            card: cardView({ id: 'a/b', name: 'tidy', latest: '1', versions: [{ v: '1', review }] } as never, false),
            state: { kind: 'idle' },
            t,
            onInstall: vi.fn(),
            onUpdate: vi.fn(),
            onUninstall: vi.fn(),
        } as never,
    } as never) as never;
}

async function mountSheet(preview: InstallPreview): Promise<void> {
    const refuse = () => Promise.reject(new Error('not used'));
    const host = {
        previewInstall: () => Promise.resolve(preview),
        install: refuse,
        uninstall: refuse,
        listProjects: () => Promise.resolve([]),
        currentProjectPath: () => Promise.resolve(null),
    } as unknown as CatalogHost;
    const target = document.createElement('div');
    document.body.appendChild(target);
    mounted = mount(InstallSheet, {
        target,
        props: { card: cardView({ id: 'a/b', name: 'tidy' }, false), host, t, close: vi.fn() },
    } as never) as never;
    await new Promise((resolve) => setTimeout(resolve, 0));
}

describe('the card mark', () => {
    test('an instructions_write finding paints the warn mark with the exact words', () => {
        mountCard(REVIEW);
        const mark = document.querySelector('[data-instructions-write-mark]');
        expect(mark?.getAttribute('aria-label')).toBe('edits your agent instruction files');
        expect(mark?.classList.contains('catalog-card__warn')).toBe(true);
    });

    test('NEGATIVE CONTROL: any other finding paints no such mark', () => {
        mountCard(OTHER_REVIEW);
        expect(document.querySelector('[data-instructions-write-mark]')).toBeNull();
    });
});

describe('the install sheet line', () => {
    test('the sheet says the skill edits the instruction files, and the install is not gated', async () => {
        await mountSheet({ body: 'read me', files: [{ path: 'SKILL.md' }], review: REVIEW });
        const line = document.querySelector('[data-instructions-write-consent]');
        expect(line?.textContent).toContain('this skill edits your agent instruction files, such as CLAUDE.md or AGENTS.md.');
        expect(document.querySelector('input[type="checkbox"]')).toBeNull();
    });

    test('NEGATIVE CONTROL: a preview whose review found something else has no such line', async () => {
        await mountSheet({ body: 'read me', files: [{ path: 'SKILL.md' }], review: OTHER_REVIEW });
        expect(document.querySelector('[data-instructions-write-consent]')).toBeNull();
    });
});

describe('the reading-pane label', () => {
    test('the kind is named, not printed as an unrecognised token', () => {
        expect(reviewKindLabel('instructions_write', t)).toBe('edits agent instruction files');
    });

    test('a kind this build does not know renders as a generic reviewer warning, not blank', () => {
        expect(reviewKindLabel('future_kind', t)).toBe('a warning kind this app does not know: future_kind');
    });
});

describe('the reviewer detail rides under the sentence as plain text', () => {
    const DETAIL_REVIEW: CatalogReview = {
        status: 'reviewed',
        verdict: 'flagged',
        warnings: [{ kind: 'instructions_write', detail: 'appends to <b>~/.claude/CLAUDE.md</b>', file: 'SKILL.md' }],
    };

    test('the sheet shows the detail as text, never markup', async () => {
        await mountSheet({ body: 'read me', files: [{ path: 'SKILL.md' }], review: DETAIL_REVIEW });
        const line = document.querySelector('[data-instructions-write-consent]');
        expect(line?.textContent).toContain('appends to <b>~/.claude/CLAUDE.md</b>');
        expect(line?.querySelector('b')).toBeNull();
    });

    test('a long detail is capped', async () => {
        const long = { ...DETAIL_REVIEW, warnings: [{ kind: 'instructions_write', detail: 'x'.repeat(900) }] };
        await mountSheet({ body: 'read me', files: [{ path: 'SKILL.md' }], review: long });
        const detail = document.querySelector('.consent__detail');
        expect((detail?.textContent ?? '').length).toBeLessThanOrEqual(200);
    });
});

describe('the notice never stops silently at the cap', () => {
    const many = (n: number): CatalogReview => ({
        status: 'reviewed',
        verdict: 'flagged',
        warnings: Array.from({ length: n }, (_, i) => ({ kind: 'instructions_write', detail: `edits AGENTS.md ${i}` })),
    });

    test('four findings show three details and "and 1 more in the review."', async () => {
        await mountSheet({ body: 'read me', files: [{ path: 'SKILL.md' }], review: many(4) });
        expect(document.querySelectorAll('.consent__detail').length).toBe(4);
        expect(document.querySelector('[data-instructions-more]')?.textContent).toBe('and 1 more in the review.');
    });

    test('NEGATIVE CONTROL: three findings say nothing about more', async () => {
        await mountSheet({ body: 'read me', files: [{ path: 'SKILL.md' }], review: many(3) });
        expect(document.querySelector('[data-instructions-more]')).toBeNull();
    });

    test('the update sheet says so too', () => {
        const sheet = updateSheet('tidy', '1', '2', t, ['a', 'b', 'c'], 2) as { lines: string[] };
        expect(sheet.lines).toEqual(['a', 'b', 'c', 'and 2 more in the review.']);
        expect((updateSheet('tidy', '1', '2', t, ['a']) as { lines: string[] }).lines).toEqual(['a']);
    });
});

describe('packs', () => {
    test('facts merge the members details, cap them, and count what is left out', () => {
        const member = (id: string, details: string[], more = 0) => ({
            item_id: id, version: '1', kind: 'skill', scripts: 0,
            instructions_write: true, instructions_details: details, instructions_more: more,
        });
        const facts = loadoutFacts(null, [member('a/x', ['1', '2']), member('a/y', ['3', '4'], 2)]);
        expect(facts.instructionsDetails).toEqual(['1', '2', '3']);
        expect(facts.instructionsMore).toBe(3);
    });

    function mountMembers(flag: boolean): void {
        const target = document.createElement('div');
        document.body.appendChild(target);
        mounted = mount(LoadoutMembers, {
            target,
            props: {
                facts: loadoutFacts(null, [{ item_id: 'a/sme', version: '1', kind: 'skill', scripts: 0, instructions_write: flag }]),
                t,
            } as never,
        } as never) as never;
    }

    test('a member whose own review edits the instruction files is marked on its row', () => {
        mountMembers(true);
        expect(document.querySelector('[data-instructions-write-mark]')?.textContent)
            .toBe('edits your agent instruction files');
    });

    test('NEGATIVE CONTROL: an unflagged member has no mark', () => {
        mountMembers(false);
        expect(document.querySelector('[data-instructions-write-mark]')).toBeNull();
    });

    test('the pack sheet shows the notice when a member, not the pack, carries the finding', async () => {
        const host = {
            previewInstall: () => Promise.resolve({
                body: '{"members":[]}',
                files: [{ path: 'loadout.json' }],
                review: OTHER_REVIEW,
                loadout_members: [{ item_id: 'a/sme', version: '1', kind: 'skill', scripts: 0, instructions_write: true, instructions_details: ['appends to ~/.claude/CLAUDE.md'], instructions_more: 1 }],
            }),
            install: () => Promise.reject(new Error('n/a')),
            uninstall: () => Promise.reject(new Error('n/a')),
            listProjects: () => Promise.resolve([]),
            currentProjectPath: () => Promise.resolve(null),
        } as unknown as CatalogHost;
        const target = document.createElement('div');
        document.body.appendChild(target);
        mounted = mount(InstallSheet, {
            target,
            props: { card: cardView({ id: 'a/pack', name: 'pack', kind: 'loadout' } as never, false), host, t, close: vi.fn() },
        } as never) as never;
        await new Promise((resolve) => setTimeout(resolve, 0));
        expect(document.querySelector('[data-instructions-write-consent]')).not.toBeNull();
        expect(document.querySelector('.consent__detail')?.textContent).toBe('appends to ~/.claude/CLAUDE.md');
        expect(document.querySelector('[data-instructions-more]')?.textContent).toBe('and 1 more in the review.');
    });
});

describe('try and one-shot', () => {
    const host = { runningSessions: () => [] } as unknown as CatalogHost;

    function open(component: unknown, flag: boolean): void {
        const target = document.createElement('div');
        document.body.appendChild(target);
        mounted = mount(component as never, {
            target,
            props: { name: 'tidy', body: 'text', files: 1, host, t, close: vi.fn(), writesInstructions: flag, instructionsDetails: ['edits MEMORY.md'] } as never,
        } as never) as never;
    }

    test.each([['TrySheet', TrySheet], ['OneShotPicker', OneShotPicker]])('%s shows the notice when flagged', (_n, component) => {
        open(component, true);
        expect(document.querySelector('[data-instructions-write-consent]')?.textContent).toContain('edits MEMORY.md');
    });

    test.each([['TrySheet', TrySheet], ['OneShotPicker', OneShotPicker]])('%s NEGATIVE CONTROL: no notice unflagged', (_n, component) => {
        open(component, false);
        expect(document.querySelector('[data-instructions-write-consent]')).toBeNull();
    });
});

describe('the manual update sheet', () => {
    test('carries the warning and the detail when the new version edits the instruction files', () => {
        const sheet = updateSheet('tidy', '1', '2', t, ['edits MEMORY.md']);
        expect(String(sheet.lead)).toContain('this skill edits your agent instruction files, such as CLAUDE.md or AGENTS.md.');
        expect(sheet.lines).toEqual(['edits MEMORY.md']);
    });

    test('NEGATIVE CONTROL: no notice by default', () => {
        const sheet = updateSheet('tidy', '1', '2', t);
        expect(String(sheet.lead)).not.toContain('MEMORY.md');
        expect(sheet.lines).toEqual([]);
    });
});
