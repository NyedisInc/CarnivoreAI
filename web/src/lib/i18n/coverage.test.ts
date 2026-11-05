import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, test } from 'vitest';

import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { isPseudo, pseudoCount, PSEUDO_LOCALE } from '../../../../client/js/i18n/pseudo.js';
import enCatalog from '../../../../client/js/i18n/catalog.en.js';
import { registerPluginSlices } from './plugin-fragments';
import { SUMMARY_KEYS } from '../../../../client/js/labels/session-summary.js';
import {
    forkFailureNotice,
    loadFailedNotice,
    RECENT_KEYS,
    recentCountLabel,
    recentCountUnavailableLabel,
    restartNotice,
    unavailableDetail,
    unidentifiedRestartNotice,
} from '../../../../client/js/labels/recent-session.js';
import {
    attentionReason,
    attentionTitle,
    archivedNoticeText,
    authorityBannerText,
    PROJECT_TREE_KEYS,
    presenceBadgeText,
    sessionCountLabel,
    workTitle,
} from '../../../../client/js/labels/project-tree.js';
import {
    RUNNING_SESSION_KEYS,
    listingAttentionDetail,
    relativeAge,
    rowActionFailed,
    runningCountLabel,
    runningCountUnavailableLabel,
} from '../../../../client/js/labels/running-session.js';

const ATTENTION_REASON = {
    listingUnreadable: 'project.attention.listing_unreadable',
    ambiguousName: 'project.attention.ambiguous_name',
    noRecord: 'project.attention.no_record',
    dirUnreadable: 'project.attention.dir_unreadable',
    noProjectId: 'project.attention.no_project_id',
    endedDirUnreadable: 'project.attention.ended_dir_unreadable',
    endedNoProjectId: 'project.attention.ended_no_project_id',
} as const;
const PROJECT_WORK_UNRECORDED_KEY = 'project.work.unrecorded';
const SESSION_WORK_UNRECORDED_KEY = 'session.work.unrecorded';
const workAttrs = (stamp: string | null, titleKey: string) =>
    stamp ? { state: 'recorded', at: stamp, titleKey: null } : { state: 'unrecorded', at: null, titleKey };
import { summaryLabel } from '../session-summary-label';
import {
    PROJECT_CREATE_KEYS,
    cloneFailure,
    nameRefusal,
    uniqueNameFailure,
} from '../../../../client/js/labels/project-create.js';
import { validateName } from '../launchpad/project-folder';

// The plugins' slices of the catalog are part of the table these assertions read.
registerPluginSlices();

const repoRoot = fileURLToPath(new URL('../../../..', import.meta.url));

import { PORTED_FILES } from './ported-files';
import {
    COMMAND_LITERALS,
    LOG_LABELS,
    looksLikeCopy,
    scannable,
    stringLiterals,
    WIRE_LITERALS,
} from './string-scan';


interface I18nLike {
    t(key: string, params?: Record<string, unknown> | null): string;
    readonly locale: string;
}


describe('the pseudo locale proves the surface really reads the catalog', () => {
    const CASES: Array<[{ bucket: string; total: number; unreadCount: number }, number]> = [
        [{ bucket: 'unknown', total: 0, unreadCount: 0 }, 1],
        [{ bucket: 'working', total: 1, unreadCount: 0 }, 3],
        [{ bucket: 'working', total: 2, unreadCount: 0 }, 3],
        [{ bucket: 'unread', total: 2, unreadCount: 1 }, 4],
        [{ bucket: 'permission', total: 19, unreadCount: 3 }, 4],
        [{ bucket: 'done', total: 1, unreadCount: 1 }, 4],
        [{ bucket: 'dead', total: 3, unreadCount: 0 }, 3],
        [{ bucket: 'input', total: 2, unreadCount: 2 }, 4],
    ];

    test('every rendered sentence is fully pseudo-localised', () => {
        const i18n = createI18n({ locale: PSEUDO_LOCALE }) as I18nLike;
        const t = (k: string, p?: Record<string, unknown> | null) => i18n.t(k, p);
        for (const [summary] of CASES) {
            const label = summaryLabel(summary, t);
            expect(isPseudo(label), `${JSON.stringify(summary)} -> ${label}`).toBe(true);
        }
    });

    test('and it is built from exactly the expected number of messages', () => {
        const i18n = createI18n({ locale: PSEUDO_LOCALE }) as I18nLike;
        const t = (k: string, p?: Record<string, unknown> | null) => i18n.t(k, p);
        for (const [summary, expected] of CASES) {
            const label = summaryLabel(summary, t);
            expect(
                pseudoCount(label),
                `${JSON.stringify(summary)} -> ${label}`,
            ).toBe(expected);
        }
    });

    test('the counts still format inside the pseudo locale', () => {
        const i18n = createI18n({ locale: PSEUDO_LOCALE }) as I18nLike;
        const t = (k: string, p?: Record<string, unknown> | null) => i18n.t(k, p);
        expect(summaryLabel({ bucket: 'working', total: 19, unreadCount: 3 }, t))
            .toContain('19');
        expect(summaryLabel({ bucket: 'working', total: 1234, unreadCount: 0 }, t))
            .toContain('1,234');
    });

    test('NEGATIVE CONTROL: an unported sentence is NOT pseudo, so the guard can fail', () => {
        expect(isPseudo('working - 2 sessions')).toBe(false);
        expect(isPseudo('⟦working ~~~⟧, 1 unread')).toBe(false);
        expect(isPseudo('⟦a ~⟧ and ⟦b ~⟧')).toBe(false);
        expect(isPseudo('')).toBe(false);
        expect(isPseudo('⟦⟦a ~⟧ - ⟦b ~⟧ ~⟧')).toBe(true);
        expect(pseudoCount('⟦⟦a ~⟧ - ⟦b ~⟧ ~⟧')).toBe(3);
    });

    test('the pseudo catalog has exactly the default catalog keys, never fewer', () => {
        const i18n = createI18n({ locale: 'en' }) as unknown as {
            catalogFor(k: string): { messages: Record<string, unknown> };
        };
        const en = Object.keys(i18n.catalogFor('en').messages).sort();
        const pseudo = Object.keys(i18n.catalogFor(PSEUDO_LOCALE).messages).sort();
        expect(pseudo).toEqual(en);
        expect(en.length).toBeGreaterThan(15);
    });
});



const RENDERED_CASE_KEYS = new Set([
    'opscenter.brand.wordmark_alt',
    'drawer.account.lurker',
    'cplug.huddle.swarm.section.alpha',
    'cplug.huddle.swarm.rank.alpha',
    'leader.mark.alpha',
    'cplug.huddle.swarm.settings.look.rank.sysop',
    'drawer.pack.alpha',
    'cplug.huddle.swarm.settings.upper_ranks_permissions',
    'opscenter.topbar.connection.title',
    'opscenter.topbar.connection.connected',
    'opscenter.topbar.connection.disconnected',
    'opscenter.topbar.connection.unknown',
    'opscenter.topbar.avatar_initial',
    'opscenter.nav.primary',
    'opscenter.nav.components_label',
    'opscenter.nav.components_hidden_label',
    'opscenter.components.title',
    'opscenter.frame.expand',
    'opscenter.frame.collapse',
    'sidebar.group.menu.label',
    'sidebar.group.rename.aria',
    'sidebar.project.rename.aria',
    'opscenter.frame.clear',
    'opscenter.frame.view_all',
    'drawer.rail.usage_context_short',
]);

const RULED_CASE_PREFIXES: readonly string[] = ['warez.elite.', 'menubar.'];

describe('a ported file may not carry a hardcoded sentence', () => {
    test.each(PORTED_FILES)('%s holds no user-visible literal', (rel) => {
        const src = fs.readFileSync(path.join(repoRoot, rel), 'utf8');
        const offenders = stringLiterals(scannable(src)).filter(looksLikeCopy);
        expect(
            offenders,
            `${rel} holds copy that should be a catalog key: ${JSON.stringify(offenders)}`,
        ).toEqual([]);
    });

    test('the list of ported files is not empty and the files exist', () => {
        // A guard that silently scanned nothing would pass forever. The
        expect(PORTED_FILES.length).toBeGreaterThanOrEqual(207);
        for (const rel of PORTED_FILES) {
            expect(fs.existsSync(path.join(repoRoot, rel)), rel).toBe(true);
        }
    });

    test('NEGATIVE CONTROL: the scanner does find a literal when there is one', () => {
        expect(stringLiterals(scannable("const a = 'no sessions';")).filter(looksLikeCopy))
            .toEqual(['no sessions']);
        for (const command of COMMAND_LITERALS) {
            expect(/[A-Za-z]{2,}\s+[A-Za-z]{2,}/.test(command), command).toBe(true);
            expect(command.includes('tmux -L cloude'), command).toBe(true);
        }
        expect(stringLiterals(scannable('<a rel="noopener noreferrer">')).filter(looksLikeCopy))
            .toEqual([]);
        expect(stringLiterals(scannable('<a title="noopener noreferrer">')).filter(looksLikeCopy))
            .toEqual(['noopener noreferrer']);
        expect(stringLiterals(scannable("t('session.summary.none');")).filter(looksLikeCopy))
            .toEqual([]);
        expect(stringLiterals(scannable("console.error('no string layer here');")).filter(looksLikeCopy))
            .toEqual([]);
        expect(stringLiterals(scannable('<!-- it says \'the folder is gone\' -->'))
            .filter(looksLikeCopy)).toEqual([]);
        expect(stringLiterals(scannable('<button class="modal-btn modal-btn-primary">'))
            .filter(looksLikeCopy)).toEqual([]);
        expect(stringLiterals(scannable('overlayClass="text-prompt-modal na-flow"'))
            .filter(looksLikeCopy)).toEqual([]);
        expect(stringLiterals(scannable('<span title="folder not found">'))
            .filter(looksLikeCopy)).toEqual(['folder not found']);
        expect(stringLiterals(scannable('<span aria-label="archive project">'))
            .filter(looksLikeCopy)).toEqual(['archive project']);
        expect(stringLiterals(scannable('<input placeholder="paste your url here">'))
            .filter(looksLikeCopy)).toEqual(['paste your url here']);
        for (const literal of WIRE_LITERALS) {
            expect(literal.split(/\s+/).length, literal).toBeLessThanOrEqual(5);
            expect(literal, literal).not.toMatch(/[.!?]$/);
        }
        const keepLabels = new Set<string>();
        for (const rel of PORTED_FILES) {
            const src = fs.readFileSync(path.join(repoRoot, rel), 'utf8');
            for (const m of src.matchAll(/keepNav\(\s*[A-Za-z0-9_]+\s*,\s*'([^']*)'/g)) {
                if (m[1] !== undefined) keepLabels.add(m[1]);
            }
        }
        for (const label of LOG_LABELS) {
            expect(/[A-Za-z]{2,}\s+[A-Za-z]{2,}/.test(label), label).toBe(true);
            expect(label.split(/\s+/).length, label).toBeLessThanOrEqual(4);
            expect(label, label).not.toMatch(/[.!?]$/);
            expect(keepLabels.has(label), `${label} is exempted but no keepNav() uses it`)
                .toBe(true);
        }
    });
});

describe('the catalog itself stays honest', () => {
    test('every key the ported surface asks for exists', () => {
        const keys = [
            SUMMARY_KEYS.none,
            SUMMARY_KEYS.sessions,
            SUMMARY_KEYS.unread,
            SUMMARY_KEYS.line,
            SUMMARY_KEYS.lineWithUnread,
        ];
        for (const key of keys) {
            expect(Object.prototype.hasOwnProperty.call(enCatalog, key), key).toBe(true);
        }
        for (const bucket of ['permission', 'input', 'working', 'unread', 'done', 'dead', 'unknown']) {
            const key = SUMMARY_KEYS.bucketPrefix + bucket;
            expect(Object.prototype.hasOwnProperty.call(enCatalog, key), key).toBe(true);
        }
    });

    test('UI copy is lowercase and plain, and a catalog is not an exemption', () => {
        for (const [key, entry] of Object.entries(enCatalog as Record<string, unknown>)) {
            const values =
                typeof entry === 'string'
                    ? [entry]
                    : entry && typeof entry === 'object'
                      ? Object.values(entry as Record<string, string>)
                      : [];
            for (const value of values) {
                if (!RENDERED_CASE_KEYS.has(key) && !RULED_CASE_PREFIXES.some((prefix) => key.startsWith(prefix))) {
                    expect(value, `${key}: ${value}`).not.toMatch(/^[A-Z]/);
                }
                expect(value, `${key}: ${value}`).not.toMatch(/[–—]/);
            }
        }
    });

    test('the case exemption list is small, real, and hides no lowercase value', () => {
        expect(RENDERED_CASE_KEYS.size).toBeLessThanOrEqual(30);
        for (const key of RENDERED_CASE_KEYS) {
            const value = (enCatalog as Record<string, unknown>)[key];
            expect(typeof value, key).toBe('string');
            expect(value as string, key).toMatch(/[A-Z]/);
        }
    });

    test('every plural set carries the mandatory `other` form', () => {
        for (const [key, value] of Object.entries(enCatalog as Record<string, unknown>)) {
            if (value && typeof value === 'object') {
                expect(
                    Object.prototype.hasOwnProperty.call(value, 'other'),
                    `${key} is a plural set with no \`other\``,
                ).toBe(true);
            }
        }
    });
});


describe('the RECENT surface really reads the catalog too', () => {
    function pseudoT(): (k: string, p?: Record<string, unknown> | null) => string {
        const i18n = createI18n({ locale: PSEUDO_LOCALE }) as I18nLike;
        return (k, p) => i18n.t(k, p);
    }

    const CASES: Array<[string, string, number]> = (() => {
        const t = pseudoT();
        return [
            ['count one', recentCountLabel(1, t), 1],
            ['count many', recentCountLabel(19, t), 1],
            ['count unavailable', recentCountUnavailableLabel(t), 1],
            ['unavailable title', t(RECENT_KEYS.unavailableTitle), 1],
            ['unavailable detail fallback', unavailableDetail(null, t), 1],
            ['load failed', loadFailedNotice(new Error('timeout'), t), 1],
            ['load failed, no message', loadFailedNotice(new Error(''), t), 2],
            ['empty with archived', t(RECENT_KEYS.emptyIncludingArchived), 1],
            ['ended', t(RECENT_KEYS.lifecycleEnded), 1],
            ['name fallback', t(RECENT_KEYS.nameFallback), 1],
            ['archive action', t(RECENT_KEYS.archiveAction), 1],
            ['archive title', t(RECENT_KEYS.archiveActionTitle), 1],
            ['archive aria', t(RECENT_KEYS.archiveActionAria), 1],
            ['archive badge', t(RECENT_KEYS.archiveBadge), 1],
            ['archive badge title', t(RECENT_KEYS.archiveBadgeTitle), 1],
            ['archive show', t(RECENT_KEYS.archiveShow), 1],
            ['archive hide', t(RECENT_KEYS.archiveHide), 1],
            ['archive no id', t(RECENT_KEYS.archiveFailedNoId), 1],
            ['restart action', t(RECENT_KEYS.restartAction), 1],
            ['restart, nothing said', restartNotice(null, t), 1],
            ['restart none_recorded', restartNotice({ conversation: 'none_recorded' }, t), 1],
            ['restart none_recorded named',
                restartNotice({ conversation: 'none_recorded', title_carried: 'Media' }, t), 1],
            ['restart unknown', restartNotice({ conversation: 'unknown' }, t), 1],
            ['restart unknown named',
                restartNotice({ conversation: 'zzz', title_carried: 'Media' }, t), 1],
            ['restart row lost',
                restartNotice({ conversation: 'resumed', row_reused: false }, t), 1],
            ['restart row lost named',
                restartNotice({ conversation: 'resumed', row_reused: false, title_carried: 'Media' }, t), 1],
            ['restart unidentified', unidentifiedRestartNotice('', t), 1],
            ['restart unidentified named', unidentifiedRestartNotice('Media', t), 1],
            ['fork 409', forkFailureNotice({ status: 409 }, t), 1],
            ['fork failed', forkFailureNotice({ message: 'boom' }, t), 1],
            ['fork failed, no message', forkFailureNotice({}, t), 2],
            ['fork lineage', t(RECENT_KEYS.forkLineageUnrecorded), 1],
        ] as Array<[string, string, number]>;
    })();

    test.each(CASES)('%s is fully pseudo-localised', (_name, rendered) => {
        expect(isPseudo(rendered), rendered).toBe(true);
    });

    test.each(CASES)('%s is built from exactly the expected message count',
        (_name, rendered, expected) => {
            expect(pseudoCount(rendered), rendered).toBe(expected);
        });

    test('a clean resume still says NOTHING, in any locale', () => {
        expect(restartNotice({ conversation: 'resumed', row_reused: true }, pseudoT()))
            .toBeNull();
    });

    test('the counts still format inside the pseudo locale', () => {
        const t = pseudoT();
        expect(recentCountLabel(19, t)).toContain('19');
        expect(recentCountLabel(1234, t)).toContain('1,234');
    });

    test("a user's own title is NOT pseudo-localised, because it is data", () => {
        expect(unidentifiedRestartNotice('Media Compression', pseudoT()))
            .toContain('Media Compression');
    });

    test('every key this surface asks for exists in the catalog', () => {
        for (const key of Object.values(RECENT_KEYS)) {
            expect(Object.prototype.hasOwnProperty.call(enCatalog, key), key).toBe(true);
        }
    });
});


describe('the PROJECT TREE really reads the catalog too', () => {
    function pseudoT(): (k: string, p?: Record<string, unknown> | null) => string {
        const i18n = createI18n({ locale: PSEUDO_LOCALE }) as I18nLike;
        return (k, p) => i18n.t(k, p);
    }

    const CASES: Array<[string, string, number]> = (() => {
        const t = pseudoT();
        return [
            ['session count one', sessionCountLabel(1, t), 1],
            ['session count many', sessionCountLabel(19, t), 1],
            ['attention title one', attentionTitle(1, t), 1],
            ['attention title many', attentionTitle(3, t), 1],
            ['archived count', archivedNoticeText({ kind: 'count', count: 2 }, t) as string, 1],
            ['archived unknown', archivedNoticeText({ kind: 'unknown' }, t) as string, 1],
            ['authority unknown', authorityBannerText({ kind: 'unknown' }, t) as string, 1],
            ['presence missing', presenceBadgeText('missing', null, t) as string, 1],
            ['presence unreachable, no reason',
                presenceBadgeText('unreachable', null, t) as string, 2],
            ['no project group', t(PROJECT_TREE_KEYS.noProject), 1],
            ['attention head', t(PROJECT_TREE_KEYS.attentionHead), 1],
            ['toggle aria', t(PROJECT_TREE_KEYS.toggleAria, { name: 'api' }), 1],
            ['empty title', t(PROJECT_TREE_KEYS.emptyTitle), 1],
            ['empty hint', t(PROJECT_TREE_KEYS.emptyHint), 1],
            ['archived badge', t(PROJECT_TREE_KEYS.badgeArchived), 1],
            ['edit action', t(PROJECT_TREE_KEYS.actionEdit), 1],
            ['archive title', t(PROJECT_TREE_KEYS.actionArchiveTitle), 1],
            ['restore title', t(PROJECT_TREE_KEYS.actionRestoreTitle), 1],
            ['archived show', t(PROJECT_TREE_KEYS.archivedShow), 1],
            ['archived hide', t(PROJECT_TREE_KEYS.archivedHide), 1],
            ['badge tmux', t(PROJECT_TREE_KEYS.badgeTmux), 1],
            ['badge external', t(PROJECT_TREE_KEYS.badgeExternal), 1],
            ['badge ended', t(PROJECT_TREE_KEYS.badgeEnded), 1],
            ['project work unrecorded',
                workTitle(workAttrs(null, PROJECT_WORK_UNRECORDED_KEY), t) as string, 1],
            ['session work unrecorded',
                workTitle(workAttrs(null, SESSION_WORK_UNRECORDED_KEY), t) as string, 1],
        ] as Array<[string, string, number]>;
    })();

    test.each(CASES)('%s is fully pseudo-localised', (_name, rendered) => {
        expect(isPseudo(rendered), rendered).toBe(true);
    });

    test.each(CASES)('%s is built from exactly the expected message count',
        (_name, rendered, expected) => {
            expect(pseudoCount(rendered), rendered).toBe(expected);
        });

    test('ALL SEVEN attention reasons are catalog messages', () => {
        const t = pseudoT();
        for (const reasonKey of Object.values(ATTENTION_REASON)) {
            const rendered = attentionReason({ reasonKey }, t);
            expect(isPseudo(rendered), `${reasonKey} -> ${rendered}`).toBe(true);
            expect(pseudoCount(rendered), reasonKey).toBe(1);
        }
    });

    test("the SERVER's own detail is NOT translated, because it is data", () => {
        const rendered = attentionReason(
            { reasonKey: ATTENTION_REASON.listingUnreadable, detail: 'the server answered HTTP 500' },
            pseudoT(),
        );
        expect(rendered).toBe('the server answered HTTP 500');
        expect(isPseudo(rendered)).toBe(false);
    });

    test("and the SERVER's authority message is not translated either", () => {
        expect(authorityBannerText(
            { kind: 'degraded', mode: 'db_unreadable', writable: false, message: 'raw' },
            pseudoT(),
        )).toBe('raw');
    });

    test('the counts still format inside the pseudo locale', () => {
        const t = pseudoT();
        expect(sessionCountLabel(19, t)).toContain('19');
        expect(sessionCountLabel(1234, t)).toContain('1,234');
        expect(archivedNoticeText({ kind: 'count', count: 1234 }, t)).toContain('1,234');
    });

    test('a project NAME is NOT pseudo-localised, because it is the user\'s text', () => {
        expect(pseudoT()(PROJECT_TREE_KEYS.toggleAria, { name: 'My Project' }))
            .toContain('My Project');
    });

    test('the three cases that must say NOTHING still say nothing, in any locale', () => {
        const t = pseudoT();
        expect(archivedNoticeText({ kind: 'silent' }, t)).toBeNull();
        expect(authorityBannerText({ kind: 'none' }, t)).toBeNull();
        expect(presenceBadgeText('unchecked', null, t)).toBeNull();
        expect(presenceBadgeText('present', null, t)).toBeNull();
        expect(workTitle(workAttrs('2026-09-01', PROJECT_WORK_UNRECORDED_KEY), t)).toBeNull();
    });

    test('every key this surface asks for exists in the catalog', () => {
        for (const key of Object.values(PROJECT_TREE_KEYS)) {
            expect(Object.prototype.hasOwnProperty.call(enCatalog, key), key).toBe(true);
        }
        for (const key of Object.values(ATTENTION_REASON)) {
            expect(Object.prototype.hasOwnProperty.call(enCatalog, key), key).toBe(true);
        }
    });
});



describe('the RUNNING SESSIONS surface really reads the catalog too', () => {
    function pseudoT(): (k: string, p?: Record<string, unknown> | null) => string {
        const i18n = createI18n({ locale: PSEUDO_LOCALE }) as I18nLike;
        return (k, p) => i18n.t(k, p);
    }

    test('the heading count is fully pseudo-localised, in both outcomes', () => {
        const t = pseudoT();
        for (const n of [0, 1, 2, 19]) {
            const rendered = runningCountLabel(n, t);
            expect(isPseudo(rendered), `${n} -> ${rendered}`).toBe(true);
            expect(pseudoCount(rendered), `${n}`).toBe(1);
        }
        expect(isPseudo(runningCountUnavailableLabel(t))).toBe(true);
    });

    test('the count still formats, and a plural set is really being selected', () => {
        const t = pseudoT();
        expect(runningCountLabel(1234, t)).toContain('1,234');
        expect(runningCountLabel(1, t)).not.toBe(runningCountLabel(2, t));
    });

    test('EVERY AGE BUCKET is a message, and the unknown one is its own', () => {
        const t = pseudoT();
        const now = 2_000_000_000_000;
        const at = (secondsAgo: number) => relativeAge(
            Math.floor(now / 1000) - secondsAgo, t, now,
        );
        for (const secondsAgo of [5, 90, 7200, 200000]) {
            const rendered = at(secondsAgo);
            expect(isPseudo(rendered), `${secondsAgo} -> ${rendered}`).toBe(true);
            expect(pseudoCount(rendered), `${secondsAgo}`).toBe(1);
        }
        const unknown = relativeAge(null, t, now);
        expect(isPseudo(unknown)).toBe(true);
        expect(unknown).not.toContain('0');
    });

    test('the four age buckets say four different things', () => {
        const t = pseudoT();
        const now = 2_000_000_000_000;
        const at = (s: number) => relativeAge(Math.floor(now / 1000) - s, t, now);
        const rendered = new Set([at(5), at(90), at(7200), at(200000)]);
        expect(rendered.size).toBe(4);
    });

    test('the attention detail wraps the SERVER text without translating it', () => {
        const t = pseudoT();
        const rendered = listingAttentionDetail(
            { ok: false, reason: 'http_503',
                detail: 'the server answered HTTP 503', sources: ['live'] },
            t,
        );
        expect(isPseudo(rendered), rendered).toBe(true);
        expect(rendered).toContain('the server answered HTTP 503');
        expect(rendered).toContain('http_503');
        expect(pseudoCount(rendered)).toBe(1);
    });

    test('and BOTH of its fallbacks are messages, not literals', () => {
        const t = pseudoT();
        const rendered = listingAttentionDetail(
            { ok: false, reason: null, detail: null, sources: [] }, t,
        );
        expect(isPseudo(rendered), rendered).toBe(true);
        expect(pseudoCount(rendered)).toBe(3);
    });

    test('a failed row action names the action through the catalog', () => {
        const t = pseudoT();
        const rendered = rowActionFailed(t('session.action.close'), 'HTTP 500', t);
        expect(isPseudo(rendered), rendered).toBe(true);
        expect(pseudoCount(rendered)).toBe(2);
        expect(rendered).toContain('HTTP 500');
    });

    test('a session LABEL is NOT pseudo-localised, because it is the user\'s text', () => {
        expect(pseudoT()(RUNNING_SESSION_KEYS.wrapperTitle, { label: 'claude (chrome)' }))
            .toContain('claude (chrome)');
    });

    test('every key this surface asks for exists in the catalog', () => {
        for (const key of Object.values(RUNNING_SESSION_KEYS)) {
            expect(Object.prototype.hasOwnProperty.call(enCatalog, key), key).toBe(true);
        }
    });

    test('and the surface asks for more than a handful of them', () => {
        expect(Object.keys(RUNNING_SESSION_KEYS).length).toBeGreaterThanOrEqual(40);
    });
});


describe('the MODALS and the CREATE flows really read the catalog', () => {
    function pseudoT(): (k: string, p?: Record<string, unknown> | null) => string {
        const i18n = createI18n({ locale: PSEUDO_LOCALE }) as I18nLike;
        return (k, p) => i18n.t(k, p);
    }

    const CASES: Array<[string, string, number]> = (() => {
        const t = pseudoT();
        return [
            ['refused: required', nameRefusal(validateName(''), t), 1],
            ['refused: slash', nameRefusal(validateName('a/b'), t), 1],
            ['refused: backslash', nameRefusal(validateName('a\\b'), t), 1],
            ['refused: null byte',
                nameRefusal(validateName(`a${String.fromCharCode(0)}b`), t), 1],
            ['refused: control', nameRefusal(validateName('a\nb'), t), 1],
            ['refused: reserved', nameRefusal(validateName('..'), t), 1],
            ['refused: leading dot', nameRefusal(validateName('.hidden'), t), 1],
            ['refused: too long', nameRefusal(validateName('x'.repeat(300)), t), 1],
            ['folder step title', t(PROJECT_CREATE_KEYS.folderTitle), 1],
            ['folder step prompt', t(PROJECT_CREATE_KEYS.folderChoosePrompt), 1],
            ['folder step no default', t(PROJECT_CREATE_KEYS.folderParentUnavailable), 1],
            ['folder step no picker', t(PROJECT_CREATE_KEYS.folderPickerUnavailable), 1],
            ['new project menu', t(PROJECT_CREATE_KEYS.newProjectTitle), 1],
            ['new session cannot determine',
                t(PROJECT_CREATE_KEYS.newSessionCannotDetermine), 1],
            ['new session none', t(PROJECT_CREATE_KEYS.newSessionNone), 1],
            ['archive confirm', t(PROJECT_CREATE_KEYS.archiveMessage, { name: 'api' }), 1],
            ['archive details', t(PROJECT_CREATE_KEYS.archiveDetails), 1],
            ['archive failed',
                t(PROJECT_CREATE_KEYS.archiveFailed, { reason: 'boom' }), 1],
            ['create failed', t(PROJECT_CREATE_KEYS.createFailed, { reason: 'boom' }), 1],
            ['clone: auth', cloneFailure(new Error('gh auth login required'), t), 1],
            ['clone: not found', cloneFailure(new Error('repository not found'), t), 1],
            ['clone: exists', cloneFailure(new Error('already exists'), t), 1],
            ['clone: no gh', cloneFailure(new Error('gh cli not installed'), t), 1],
            ['clone: timeout', cloneFailure(new Error('timed out'), t), 1],
            ['clone: nothing said', cloneFailure(new Error(''), t), 1],
            ['THE THROWN SENTENCE',
                uniqueNameFailure({ cloudeKey: PROJECT_CREATE_KEYS.uniqueNameFailed }, t), 1],
        ] as Array<[string, string, number]>;
    })();

    test.each(CASES)('%s is fully pseudo-localised', (_name, rendered) => {
        expect(isPseudo(rendered), rendered).toBe(true);
    });

    test.each(CASES)('%s is built from exactly its own messages', (_name, rendered, count) => {
        expect(pseudoCount(rendered), rendered).toBe(count);
    });

    test('an ACCEPTED name says nothing at all', () => {
        expect(nameRefusal(validateName('Punchlist Test'), pseudoT())).toBe(null);
    });

    test("the SERVER's own detail is passed through verbatim, not translated", () => {
        const t = pseudoT();
        expect(cloneFailure(new Error('HTTP 500: the disk is on fire'), t)).toBe(
            'the disk is on fire',
        );
    });

    test('a thrown error with no key keeps its own message', () => {
        expect(uniqueNameFailure(new Error('disk is full'), pseudoT())).toBe('disk is full');
    });
});
