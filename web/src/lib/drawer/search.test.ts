/** @vitest-environment jsdom */
import { describe, expect, it } from 'vitest';
import { freshDrawer } from './test-support';

async function makeSandbox(opts: { label?: (row: Record<string, unknown>) => string | null; i18n?: unknown } = {}) {
    const Win: Record<string, unknown> = {};
    if (opts.label) Win.SessionLabel = { resolve: opts.label };
    if (opts.i18n) Win.CloudeI18n = opts.i18n;
    const d = await freshDrawer(Win);
    return { Search: d.Search, Win };
}

describe('the drawer search', () => {
    it('matchesRow: case-insensitive substring on the display and tmux names, the project and the folder', async () => {
        const { Search } = await makeSandbox({ label: (row) => (row.label as string) || null });
        const row = { name: 'cloude_example_app', label: 'Example App', project_name: 'Studio-UI' };
        expect(Search.matchesRow(row, Search.normalize('exam')), 'matches the display name').toBe(true);
        expect(Search.matchesRow(row, Search.normalize('EXAMPLE_APP')), 'matches the tmux handle without its prefix, case-insensitively').toBe(true);
        expect(Search.matchesRow(row, Search.normalize('studio')), 'a project name matches').toBe(true);
        expect(Search.matchedField(row, Search.normalize('studio'))).toBe('project');
        expect(Search.matchedField(row, Search.normalize('exam'))).toBe('name');
        const placed = { ...row, working_dir: '/Users/x/dev/billing-api' };
        expect(Search.matchesRow(placed, Search.normalize('billing')), 'a folder matches').toBe(true);
        expect(Search.matchedField(placed, Search.normalize('billing'))).toBe('folder');
        expect(Search.matchesRow({ ...placed, asleep: true }, Search.normalize('billing')), 'an asleep row matches like any other').toBe(true);
        expect(Search.matchesRow(row, Search.normalize('zzz-nothing'))).toBe(false);
        expect(Search.matchesRow(row, ''), 'an empty query matches everything').toBe(true);
        expect(Search.matchesRow(null, Search.normalize('x')), 'a null row never matches a real query').toBe(false);
    });

    it('matchesRow falls back to the tmux name when SessionLabel is absent', async () => {
        const { Search } = await makeSandbox({});
        const row = { name: 'cloude_orchard', label: 'ignored, no SessionLabel loaded', project_name: null };
        expect(Search.matchesRow(row, Search.normalize('orchard'))).toBe(true);
    });

    it("a saved Layout matches on its members' names (D42)", async () => {
        const { Search } = await makeSandbox({});
        const row = { name: 'layout:L1', kind: 'layout', member_names: ['api work', 'docs'] };
        expect(Search.matchesRow(row, Search.normalize('docs'))).toBe(true);
        expect(Search.matchesRow({ ...row, kind: 'agent' }, Search.normalize('docs')), 'only a Layout row reads members').toBe(false);
    });

    it('matchesLabel: case-insensitive substring, empty query always matches', async () => {
        const { Search } = await makeSandbox({});
        expect(Search.matchesLabel('pinned', Search.normalize('PIN'))).toBe(true);
        expect(Search.matchesLabel('work stuff', Search.normalize('stuff'))).toBe(true);
        expect(Search.matchesLabel('work stuff', Search.normalize('nope'))).toBe(false);
        expect(Search.matchesLabel('anything', '')).toBe(true);
        expect(Search.matchesLabel(null, Search.normalize('x'))).toBe(false);
    });

    it('setQuery normalizes (trims, lowercases) before comparing and storing', async () => {
        const { Search } = await makeSandbox({});
        Search.setQuery('  Example  ');
        expect(Search.getQuery()).toBe('example');
    });

    it('setQuery repaints through the drawer controller on a real change', async () => {
        const { Search, Win } = await makeSandbox({});
        let calls = 0;
        Win.SessionSidebar = { repaint: () => { calls += 1; } };
        Search.setQuery('orchard');
        expect(calls).toBe(1);
        expect(Search.getQuery()).toBe('orchard');
    });

    it('setQuery is a no-op, and skips the repaint, when the normalized value is unchanged', async () => {
        const { Search, Win } = await makeSandbox({});
        let calls = 0;
        Win.SessionSidebar = { repaint: () => { calls += 1; } };
        Search.setQuery('Orchard');
        expect(calls).toBe(1);
        Search.setQuery('orchard');
        expect(calls, 'retyping the same text (or an input firing twice) must not force a second repaint').toBe(1);
        Search.setQuery('  ORCHARD  ');
        expect(calls, 'whitespace/case differences that normalize the same must not force a repaint either').toBe(1);
    });

    it('a missing drawer controller never throws - the write lands, the repaint is skipped', async () => {
        const { Search } = await makeSandbox({});
        expect(() => Search.setQuery('anything')).not.toThrow();
        expect(Search.getQuery()).toBe('anything');
    });

    it('noMatchesHtml: names the query, escapes it, and degrades without a i18n runtime', async () => {
        const { Search: withI18n } = await makeSandbox({
            i18n: { t: (key: string, params: unknown) => `${key}:${JSON.stringify(params)}` },
        });
        expect(withI18n.noMatchesHtml('orchard')).toMatch(/drawer\.search\.no_matches/);
        expect(withI18n.noMatchesHtml('orchard')).toMatch(/"query":"orchard"/);

        const { Search: bare } = await makeSandbox({});
        const html = bare.noMatchesHtml('<script>');
        expect(html).toMatch(/no agents match/);
        expect(html.includes('<script>'), 'a query carrying markup must come back escaped').toBe(false);
        expect(html).toMatch(/&lt;script&gt;/);
    });
});
