/** @vitest-environment jsdom */
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { afterEach, describe, expect, it, vi } from 'vitest';
import enCatalog from '../../../../client/js/i18n/catalog.en.js';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { catalogHashItem } from '../catalog/screen-host';
import { nodeHash, parseNodeHash, PUBLISH_TABS, type MenuNode } from '../catalog/menu/route';
import { openPublishPage } from '../catalog/publish-entry';
import { createActions } from './actions';
import { parseMine, parseMineRow } from './api';
import { parseLimits, parseRules } from './api-author';
import { parseFacts } from './api-facts';
import { agoText, bytesText, clockText, dateText, kibText } from './format';
import type { PageHost } from './host';
import { failureKey, FAILURE_KEYS, folderKey, HELD_REASONS, heldKey, monthKey, tabKey } from './keys';
import { reduced } from './motion';
import { createPageStore } from './page-store.svelte';
import { findingLine, GATE_IDS, gateLabelKey, gateLooksAtKey, resultKey, resultOf, resultsOf, type CheckResult } from './report-format';
import { bucketKey, bucketOf, BUCKETS, canWithdraw, isOpen, rowWord, STAGES, stageKey, stageOf, versionStage } from './stages';

const catalog = enCatalog as Record<string, unknown>;
const i18n = createI18n({ locale: 'en' }) as { t(key: string, params?: Record<string, unknown> | null): string };
const t = (key: string, params?: Record<string, unknown> | null): string => i18n.t(key, params);
const here = (rel: string): string => fileURLToPath(new URL(rel, import.meta.url));
const has = (key: string): boolean => Object.prototype.hasOwnProperty.call(catalog, key);

afterEach(() => {
    vi.unstubAllGlobals();
    globalThis.location.hash = '';
});

describe('the address', () => {
    it('round trips the page, each tab, an item and the rules', () => {
        const nodes: [MenuNode, string][] = [
            [{ scope: 'publish', page: 'tab', tab: 'submissions' }, '#warez/publish'],
            [{ scope: 'publish', page: 'tab', tab: 'skills' }, '#warez/publish/skills'],
            [{ scope: 'publish', page: 'tab', tab: 'themes' }, '#warez/publish/themes'],
            [{ scope: 'publish', page: 'tab', tab: 'mods' }, '#warez/publish/mods'],
            [{ scope: 'publish', page: 'tab', tab: 'plugins' }, '#warez/publish/plugins'],
            [{ scope: 'publish', page: 'item', tab: 'plugins', location: 'cplug:repo-pulse' }, '#warez/publish/plugins/cplug%3Arepo-pulse'],
            [{ scope: 'publish', page: 'item', tab: 'submissions', location: 'skill:x', event: 'ab12:gates' }, '#warez/publish/submissions/skill%3Ax/ab12%3Agates'],
            [{ scope: 'publish', page: 'rules' }, '#warez/publish/rules'],
        ];
        for (const [node, hash] of nodes) {
            expect(nodeHash(node)).toBe(hash);
            expect(parseNodeHash(hash)).toEqual(node);
        }
        expect(PUBLISH_TABS).toHaveLength(5);
    });

    it('treats publish/x as a publish node, never a catalog item', () => {
        expect(parseNodeHash('#warez/publish/x')).toEqual({ scope: 'publish', page: 'tab', tab: 'submissions' });
        expect(catalogHashItem('#warez/publish/x')).toBeNull();
        expect(catalogHashItem('#warez/publish')).toBeNull();
        expect(catalogHashItem('#warez/acme/sme')).toBe('acme/sme');
    });

    it('openPublishPage writes the tab fragment', () => {
        openPublishPage('themes');
        expect(globalThis.location.hash).toBe('#warez/publish/themes');
        openPublishPage();
        expect(globalThis.location.hash).toBe('#warez/publish');
    });
});

describe('the four stages (D1)', () => {
    const cases: [string, string | undefined, string | null][] = [
        ['pending', 'received', 'submitted'],
        ['pending', 'gating', 'in_review'],
        ['pending', 'awaiting_approval', 'in_review'],
        ['pending', 'stuck', 'in_review'],
        ['pending', '', 'in_review'],
        ['pending', undefined, 'in_review'],
        ['pending', 'some_new_state', 'in_review'],
        ['publishing', undefined, 'in_review'],
        ['approved', undefined, 'approved'],
        ['published', undefined, 'approved'],
        ['gate_failed', undefined, 'rejected'],
        ['rejected', undefined, 'rejected'],
        ['revoked', undefined, 'rejected'],
        ['withdrawn', undefined, null],
        ['superseded', undefined, null],
    ];
    it.each(cases)('status %s with gate_state %s is %s', (status, gate_state, stage) => {
        expect(stageOf({ status, gate_state })).toBe(stage);
    });

    it('draws a media-only row as no row, whatever its status', () => {
        for (const status of ['pending', 'approved', 'rejected']) expect(stageOf({ status, media_only: true })).toBeNull();
    });

    it('keeps a superseded version under versions sent at the stage it reached', () => {
        expect(versionStage({ status: 'superseded' })).toBe('approved');
        expect(versionStage({ status: 'rejected' })).toBe('rejected');
    });

    it('opens, withdraws and groups by the real statuses', () => {
        expect(isOpen({ status: 'publishing' })).toBe(true);
        expect(canWithdraw({ status: 'pending' })).toBe(true);
        expect(canWithdraw({ status: 'approved' })).toBe(true);
        expect(canWithdraw({ status: 'publishing' })).toBe(false);
        expect(canWithdraw({ status: 'rejected' })).toBe(false);
        expect(bucketOf({ status: 'gate_failed' })).toBe('needs_you');
        expect(bucketOf({ status: 'rejected', appeals_left: 1 })).toBe('needs_you');
        expect(bucketOf({ status: 'rejected', appeals_left: 0 })).toBe('rejected');
        expect(bucketOf({ status: 'rejected', appeals_left: null })).toBe('rejected');
        expect(bucketOf({ status: 'pending', gate_state: 'received' })).toBe('submitted');
        expect(bucketOf({ status: 'approved' })).toBe('approved');
    });

    it('words a row by the stage or by the three non-stage words', () => {
        expect(rowWord(null, 'none')).toBe('publish.page.row.on_computer');
        expect(rowWord(null, 'checked')).toBe('publish.page.row.checked_ready');
        expect(rowWord({ status: 'approved' }, 'checked')).toBe('publish.page.stage.approved');
        expect(rowWord({ status: 'rejected' }, 'checked')).toBe('publish.page.row.checked_ready');
        expect(rowWord({ status: 'pending', gate_state: 'received' }, 'refused')).toBe('publish.page.row.check_failed');
        expect(rowWord({ status: 'pending', gate_state: 'gating' })).toBe('publish.page.stage.in_review');
    });
});

describe('the catalog has every key the helpers return', () => {
    it('stages, groups, row words, tabs, held reasons, failures, months, folders', () => {
        const keys = [
            ...STAGES.map(stageKey),
            ...BUCKETS.map(bucketKey),
            ...PUBLISH_TABS.map(tabKey),
            ...HELD_REASONS.map(heldKey),
            ...FAILURE_KEYS.map(failureKey),
            ...Array.from({ length: 12 }, (_, i) => monthKey(i)),
            ...(['skill', 'theme', 'mod', 'plugin'] as const).map(folderKey),
            rowWord(null, 'none'), rowWord(null, 'checked'), rowWord(null, 'refused'),
        ];
        for (const key of keys) expect(has(key), key).toBe(true);
    });

    it('the twelve gates in the real order, their labels, sentences and the result words', () => {
        expect([...GATE_IDS]).toEqual(['structure', 'schema', 'kind_rules', 'identity', 'digest', 'static_scans', 'secrets', 'license', 'dependencies', 'ai_review', 'clean_room', 'grade']);
        for (const gate of GATE_IDS) {
            expect(has(gateLabelKey(gate)), gate).toBe(true);
            expect(has(gateLooksAtKey(gate)), gate).toBe(true);
        }
        const results: CheckResult[] = ['passed', 'did_not_pass', 'note', 'skipped', 'not_run', 'running'];
        for (const r of results) expect(has(resultKey(r)), r).toBe(true);
        expect(t(gateLabelKey('clean_room'))).toBe('clean room');
    });

    it('maps a gate to its result: a missing gate is not run, never passed; clean room skipped by policy is skipped', () => {
        const gate = (id: string, verdict: string, code = ''): never => ({ id, verdict, code, fix: '', findings: [] }) as never;
        expect(resultOf(undefined)).toBe('not_run');
        expect(resultOf(undefined, true)).toBe('running');
        expect(resultOf(gate('license', 'pass'))).toBe('passed');
        expect(resultOf(gate('license', 'fail'))).toBe('did_not_pass');
        expect(resultOf(gate('license', 'undetermined'))).toBe('did_not_pass');
        expect(resultOf(gate('license', 'advisory'))).toBe('note');
        expect(resultOf(gate('clean_room', 'advisory', 'skipped_by_policy'))).toBe('skipped');
        const only = resultsOf([gate('structure', 'pass')]);
        expect(only[0]).toBe('passed');
        expect(only.slice(1).every((r) => r === 'not_run')).toBe(true);
        expect(resultsOf(null, true).every((r) => r === 'running')).toBe(true);
        expect(findingLine({ code: 'license_missing', path: 'SKILL.md', line: 3 })).toBe('license_missing  SKILL.md:3');
    });
});

function fakeHost(over: Partial<PageHost> = {}): { host: PageHost; calls: Record<string, number> } {
    const calls: Record<string, number> = {};
    const count = <T>(name: string, value: T) => (): Promise<T> => { calls[name] = (calls[name] ?? 0) + 1; return Promise.resolve(value); };
    const host = {
        catalogSession: count('session', { signed_in: true }),
        account: count('account', { handle: 'acme', handle_status: 'confirmed', registered: true }),
        mine: count('mine', parseMine({ submissions: [{ submission_id: 'ab12', status: 'pending', gate_state: 'gating', kind: 'skill', name: 'x' }] })),
        listSkills: count('folders', { skills: [] }),
        limits: count('limits', parseLimits({ per_day: 5, used_today: 1 })),
        rules: count('rules', parseRules({ kinds: [{ kind: 'skill', open: true }] })),
        facts: (loc: string) => { calls.facts = (calls.facts ?? 0) + 1; return Promise.resolve(parseFacts({}, loc)); },
        report: (id: string) => { calls.report = (calls.report ?? 0) + 1; return Promise.resolve({ outcome: 'pass', gates: [], id }); },
        preview: count('preview', { can_send: true }),
        send: count('send', { submission_id: 'ab12' }),
        sendHero: count('media', { submission_id: 'cd34' }),
        appeal: count('appeal', undefined),
        withdraw: count('withdraw', undefined),
        register: count('register', { handle: 'acme', handle_status: 'pending', registered: true }),
        ...over,
    } as unknown as PageHost;
    return { host, calls };
}

function build(over: Partial<PageHost> = {}) {
    const { host, calls } = fakeHost(over);
    const navigate = vi.fn();
    const store = createPageStore({ host, navigate, t });
    const actions = createActions({ store, host, t });
    return { store, actions, navigate, calls, host };
}

describe('the page store: transitions write the matching node', () => {
    it('setTab, select, openEvent, openRules, closeRules and goList each navigate', () => {
        const { store, navigate } = build();
        store.setTab('themes');
        expect(navigate).toHaveBeenLastCalledWith({ scope: 'publish', page: 'tab', tab: 'themes' });
        store.select('theme:neon', 'sub1', 'themes');
        expect(navigate).toHaveBeenLastCalledWith({ scope: 'publish', page: 'item', tab: 'themes', location: 'theme:neon' });
        store.openEvent('sub1:gates');
        expect(navigate).toHaveBeenLastCalledWith({ scope: 'publish', page: 'item', tab: 'themes', location: 'theme:neon', event: 'sub1:gates' });
        store.openRules();
        expect(navigate).toHaveBeenLastCalledWith({ scope: 'publish', page: 'rules' });
        store.closeRules();
        expect(navigate).toHaveBeenLastCalledWith({ scope: 'publish', page: 'item', tab: 'themes', location: 'theme:neon', event: 'sub1:gates' });
        store.goList();
        expect(navigate).toHaveBeenLastCalledWith({ scope: 'publish', page: 'tab', tab: 'themes' });
        expect(navigate).toHaveBeenCalledTimes(6);
    });

    it('a tab click while the rules are open closes them (r3 ruling 3); close restores the opened step and the view', () => {
        const { store } = build();
        store.select('skill:a', null, 'skills');
        store.openEvent('s1:gates');
        store.openRules();
        expect(store.rulesOpen).toBe(true);
        expect(store.from).toEqual({ mid: { ev: 's1:gates' }, view: 'dossier' });
        store.setTab('mods');
        expect(store.rulesOpen).toBe(false);
        expect(store.tab).toBe('mods');
        store.select('skill:a', null, 'skills');
        store.openEvent('s1:gates');
        store.openRules();
        store.closeRules();
        expect(store.rulesOpen).toBe(false);
        expect(store.mid).toEqual({ ev: 's1:gates' });
        expect(store.view).toBe('dossier');
    });

    it('restoring from a hash writes nothing back and sets no scroll or flash flag', () => {
        const { store, navigate } = build();
        store.applyNode({ scope: 'publish', page: 'item', tab: 'plugins', location: 'cplug:repo-pulse', event: 'a:gates' });
        expect(store.tab).toBe('plugins');
        expect(store.sel).toBe('cplug:repo-pulse');
        expect(store.mid).toEqual({ ev: 'a:gates' });
        store.applyNode({ scope: 'publish', page: 'rules' });
        expect(store.rulesOpen).toBe(true);
        store.applyNode({ scope: 'publish', page: 'tab', tab: 'skills' });
        expect(store.rulesOpen).toBe(false);
        expect(store.sel).toBeNull();
        expect(navigate).not.toHaveBeenCalled();
        expect(store.scrollToTop).toBe(false);
        expect(store.flash).toBeNull();
        store.select('skill:a');
        expect(store.scrollToTop).toBe(true);
        expect(store.flash).toBe('skill:a');
    });

    it('a node the transition just wrote comes back and changes nothing', () => {
        const { store } = build();
        store.select('skill:a', null, 'skills');
        store.openRules();
        store.closeRules();
        store.goList();
        store.select('skill:a', 'sub9');
        store.applyNode({ scope: 'publish', page: 'item', tab: 'skills', location: 'skill:a' });
        expect(store.selSub).toBe('sub9');
    });
});

describe('the page store: each reload trigger reloads exactly its sources (D25)', () => {
    it('open reads the session, account, mine, folders, limits and rules once', async () => {
        const { store, calls } = build();
        await store.open();
        expect(calls).toEqual({ session: 1, account: 1, mine: 1, folders: 1, limits: 1, rules: 1 });
        expect(store.signedIn).toBe(true);
        expect(store.mine).toHaveLength(1);
    });

    it('signed out asks neither the account, the list nor the limits', async () => {
        const { store, calls } = build({ catalogSession: () => Promise.resolve({ signed_in: false }) } as never);
        await store.open();
        expect(calls.account).toBeUndefined();
        expect(calls.mine).toBeUndefined();
        expect(calls.limits).toBeUndefined();
        expect(calls.folders).toBe(1);
        expect(calls.rules).toBe(1);
    });

    it('a catalog_submissions push reloads mine then limits; the folder topics reload the folders; nothing else moves', async () => {
        const { store, calls } = build();
        await store.open();
        for (const k of Object.keys(calls)) delete calls[k];
        await store.onTopic('catalog_submissions');
        expect(calls).toEqual({ mine: 1, limits: 1 });
        for (const topic of ['local_skills', 'themes', 'mods']) await store.onTopic(topic);
        expect(calls).toEqual({ mine: 1, limits: 1, folders: 3 });
        await store.onTopic('something_else');
        expect(calls).toEqual({ mine: 1, limits: 1, folders: 3 });
    });

    it('select reads that item facts; opening the 12 checks reads its report', async () => {
        const { store, calls } = build();
        store.select('skill:a', null, 'skills');
        await vi.waitFor(() => expect(calls.facts).toBe(1));
        store.openEvent('ab12:gates');
        await vi.waitFor(() => expect(calls.report).toBe(1));
        await vi.waitFor(() => expect(store.reports.ab12).toBeDefined());
    });

    it('a row leaving gating reloads its report', async () => {
        let rows = parseMine({ submissions: [{ submission_id: 'ab12', status: 'pending', gate_state: 'gating' }] });
        const { store, calls } = build({ mine: () => Promise.resolve(rows) } as never);
        await store.open();
        expect(calls.report).toBeUndefined();
        rows = parseMine({ submissions: [{ submission_id: 'ab12', status: 'pending', gate_state: 'awaiting_approval' }] });
        await store.onTopic('catalog_submissions');
        await vi.waitFor(() => expect(calls.report).toBe(1));
    });

    it('send, media, appeal and withdraw reload mine, limits and that item facts; register reloads the account and limits', async () => {
        const { store, actions, calls } = build();
        store.select('skill:a', null, 'skills');
        await vi.waitFor(() => expect(calls.facts).toBe(1));
        const reset = (): void => { for (const k of Object.keys(calls)) delete calls[k]; };
        reset();
        expect((await actions.send({ location: 'skill:a', version: '1.0.0', digest: 'd' })).ok).toBe(true);
        expect(calls).toEqual({ send: 1, mine: 1, limits: 1, facts: 1 });
        reset();
        await actions.media('skill:a', { kind: 'skill', name: 'a', image_base64: 'AAAA' });
        expect(calls).toEqual({ media: 1, mine: 1, limits: 1, facts: 1 });
        reset();
        await actions.appeal('ab12', 'fixed it');
        expect(calls).toEqual({ appeal: 1, mine: 1, limits: 1, facts: 1 });
        reset();
        await actions.withdraw('ab12');
        expect(calls).toEqual({ withdraw: 1, mine: 1, limits: 1, facts: 1 });
        reset();
        await actions.register({ handle: 'acme' });
        expect(calls).toEqual({ register: 1, account: 1, limits: 1 });
        reset();
        await actions.refresh();
        expect(calls).toEqual({ session: 1, account: 1, mine: 1, folders: 1, limits: 1, rules: 1, facts: 1 });
    });

    it('a failing source sets only its own failure, and a failing action records its code and sentence', async () => {
        const { store, actions } = build({ limits: () => Promise.reject(new Error('boom')) } as never);
        await store.open();
        expect(store.failure.limits).toContain('your limits could not be read');
        for (const source of ['account', 'mine', 'folders', 'rules', 'facts', 'report'] as const) expect(store.failure[source], source).toBeNull();
        const refused = build({ withdraw: () => Promise.reject({ detail: { code: 'not_withdrawable' }, message: 'x' }) } as never);
        const result = await refused.actions.withdraw('ab12', 'skill:a');
        expect(result).toMatchObject({ ok: false, code: 'not_withdrawable' });
        expect(refused.store.failure.withdraw).toContain('can no longer be withdrawn');
        void actions;
    });

    it('a 429 on mine reads as the rate limit line, never a blank', async () => {
        const { store } = build({ mine: () => Promise.reject(Object.assign(new Error('x'), { status: 429 })) } as never);
        await store.open();
        expect(store.failure.mine).toBe(t('publish.page.failure.mine_rate_limited'));
    });

    it('connect registers the two pushes and tears both down', () => {
        const { store } = build();
        const stops = [vi.fn(), vi.fn()];
        const seen: (readonly string[])[] = [];
        const push = { pushOrPoll: vi.fn((_refresh: () => void, _ms: number, topics: readonly string[]) => { seen.push(topics); return stops[seen.length - 1]!; }) };
        const off = store.connect(push);
        expect(seen).toEqual([['catalog_submissions'], ['local_skills', 'themes', 'mods']]);
        off();
        expect(stops[0]).toHaveBeenCalledOnce();
        expect(stops[1]).toHaveBeenCalledOnce();
    });
});

describe('the parsers', () => {
    it('parse the golden mine row with every field present', () => {
        const golden = JSON.parse(readFileSync(here('../../../../tests/fixtures/publish_page/mine_row.json'), 'utf8')) as Record<string, unknown>;
        const row = parseMineRow(golden)!;
        expect(row).toMatchObject({
            id: golden.submission_id, status: 'rejected', gate_state: 'awaiting_approval', item_id: 'bob/work', kind: 'skill', name: 'work',
            version: '1.2.0', new_version: true, media_only: false, appeals_left: 1, created_at: golden.created_at, decided_at: golden.decided_at,
        });
        for (const field of ['reason', 'published_at', 'revoked_at', 'revocation_reason'] as const) expect(row[field], field).toBe('');
        expect(row.events).toHaveLength(5);
        expect(row.events[3]).toEqual({ at: '2026-10-21T10:00:00Z', what: 'rejected', reason: 'no license' });
        expect(row.events[4]).toEqual({ at: '2026-10-21T11:00:00Z', what: 'appealed', text: 'license added' });
    });

    it('bound every string, keep the newest 40 events, drop a row with no id, and never guess appeals_left', () => {
        const long = 'x'.repeat(5000);
        const events = Array.from({ length: 60 }, (_, i) => ({ at: 't', what: `e${i}`, text: long }));
        const rows = parseMine({ submissions: [{ submission_id: 'a', name: long, reason: long, events }, { name: 'no id' }, 'junk', null] });
        expect(rows).toHaveLength(1);
        expect(rows[0]!.name.length).toBeLessThanOrEqual(120);
        expect(rows[0]!.reason.length).toBeLessThanOrEqual(400);
        expect(rows[0]!.events).toHaveLength(40);
        expect(rows[0]!.events[39]!.what).toBe('e59');
        expect(rows[0]!.events[0]!.text!.length).toBeLessThanOrEqual(400);
        expect(rows[0]!.appeals_left).toBeNull();
        expect(parseMine(null)).toEqual([]);
    });

    it('parse limits, rules and facts without guessing a missing number', () => {
        expect(parseLimits({}).used_today).toBeNull();
        expect(parseLimits({ per_day: 5, new_account: true, media_per_day: 5 })).toMatchObject({ per_day: 5, new_account: true, media_per_day: 5, media_used_today: null });
        expect(parseRules({ kinds: [{ kind: 'skill', open: true }, { kind: 'mod' }], caps: { max_bytes: 1048576, bad: 'x' } })).toEqual({
            kinds: [{ kind: 'skill', open: true }, { kind: 'mod', open: false }], caps: { max_bytes: 1048576 },
        });
        expect(parseFacts({ declared_version: '1.2.0', changed_files: 3 }, 'skill:a')).toMatchObject({ location: 'skill:a', declared_version: '1.2.0', changed_files: 3, checks: [], sends: [] });
    });
});

describe('formats and motion', () => {
    it('words a date, a clock time, a relative time and a size', () => {
        const stamp = '2026-10-24T15:30:00';
        expect(dateText(stamp, t)).toBe('24 oct');
        expect(clockText(stamp, t)).toBe('15:30');
        const now = new Date('2026-10-24T18:30:00').getTime();
        expect(agoText(stamp, now, t)).toBe('3 hours ago');
        expect(agoText(now - 1000, now, t)).toBe('just now');
        expect(agoText(now - 60_000, now, t)).toBe('1 minute ago');
        expect(agoText(now - 2 * 86_400_000, now, t)).toBe('2 days ago');
        expect(agoText('not a date', now, t)).toBe('');
        expect(bytesText(12345, t)).toBe('12,345 bytes');
        expect(kibText(524288, t)).toBe('512 KiB');
    });

    it('reduced follows the media query', () => {
        vi.stubGlobal('matchMedia', (q: string) => ({ matches: q.includes('reduce') }));
        expect(reduced()).toBe(true);
        vi.stubGlobal('matchMedia', () => ({ matches: false }));
        expect(reduced()).toBe(false);
    });

    it('no stylesheet of the page splits a word', () => {
        const dir = here('./');
        const sheets = readdirSync(dir).filter((f) => f.endsWith('.css'));
        expect(sheets.length).toBeGreaterThan(0);
        for (const sheet of sheets) {
            const css = readFileSync(dir + sheet, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
            expect(css, sheet).not.toMatch(/overflow-wrap:\s*anywhere|break-word|word-break:\s*break-all/);
        }
    });
});

describe('a stored clean check that kept its digest (X5-54)', () => {
    const record = (over: Record<string, unknown> = {}) => ({ version: '1.0.0', ok: true, at: '2026-10-20T10:00:00Z', summary: 'clean', grade: 'B', files: 3, bytes: 142, digest: 'd'.repeat(64), findings: [], ...over });
    const facts = (checks: unknown[], sends: unknown[] = []) => (loc: string) => Promise.resolve(parseFacts({ checks, sends }, loc));

    it('lands the wizard on a sendable check after a reload, with the stored digest', async () => {
        const { store } = build({ facts: facts([record()]) } as never);
        await store.loadFacts('skill:a');
        expect(store.checks['skill:a']?.preview?.digest).toBe('d'.repeat(64));
        expect(store.checks['skill:a']).toMatchObject({ ok: true, version: '1.0.0' });
    });

    it('stays unchecked for an old record with no digest, a refused one, one older than the newest send, or one a send refused as changed', async () => {
        for (const checks of [[record({ digest: '' })], [record({ ok: false })]]) {
            const { store } = build({ facts: facts(checks) } as never);
            await store.loadFacts('skill:a');
            expect(store.checks['skill:a']).toBeUndefined();
        }
        const sent = build({ facts: facts([record()], [{ submission_id: 'a'.repeat(32), version: '1.0.0', sent_at: '2026-10-21T10:00:00Z' }]) } as never);
        await sent.store.loadFacts('skill:a');
        expect(sent.store.checks['skill:a']).toBeUndefined();
        const stale = build({ facts: facts([record()]), send: () => Promise.reject(Object.assign(new Error('x'), { detail: { code: 'folder_changed' } })) } as never);
        await stale.store.loadFacts('skill:a');
        delete stale.store.checks['skill:a'];
        await stale.actions.send({ location: 'skill:a', version: '1.0.0', digest: 'd'.repeat(64) });
        await stale.store.loadFacts('skill:a');
        expect(stale.store.checks['skill:a']).toBeUndefined();
    });
});
