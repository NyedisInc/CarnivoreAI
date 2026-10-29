/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { createRawSnippet, flushSync, mount, unmount } from 'svelte';
import GroupSection from './GroupSection.svelte';
import TitleActions from './TitleActions.svelte';
import SessionsPage from './SessionsPage.svelte';
import { SessionsData, agentQuery } from './sessions-data.svelte';
import { archivedBand, projectBands } from './inactive-projects';
import { storeFolds, storedFold } from './folds';
import type { HistoryApi, HistoryPage, HistoryProject } from '../projects-shared/history-api';
import { group, session } from '../projects-shared/test-fixtures';
import type { LensGroup } from './lenses';
import { t, setLocale } from '../i18n/index.svelte';

setLocale('en');

const folds = vi.hoisted(() => ({ list: [] as string[], saves: [] as Array<[string[], string[]]> }));
vi.mock('../drawer/store', () => ({
    viewCollapsed: () => folds.list,
    setCollapsedMany: (add: string[], remove: string[]) => {
        folds.saves.push([add, remove]);
        folds.list = folds.list.filter((k) => !remove.includes(k)).concat(add);
        return true;
    },
    current: () => ({ pinned: [], ids: {} }),
}));

const proj = (id: number, name: string, extra: Partial<HistoryProject> = {}): HistoryProject => ({ id, name, root: null, description: null, archived_at: null, last_opened_at: null, created_at: null, default_theme: null, ...extra });
const lensGroup = (p: HistoryProject, live = 0, at: string | null = null): LensGroup =>
    ({ key: `project:${p.id}`, label: p.name, bits: [], measure: '', rows: at ? [{ s: { last_activity_at: at } }] : [], count: live, live, project: p, provider: null }) as unknown as LensGroup;

let handle: ReturnType<typeof mount> | null = null;
afterEach(() => {
    if (handle) void unmount(handle);
    handle = null;
    document.body.innerHTML = '';
    folds.list = [];
    folds.saves = [];
});

describe('the query and the data layer', () => {
    test('asks for archived projects, and for automated runs only while show hidden is on', () => {
        expect(new URLSearchParams(agentQuery(0, false)).get('project_state')).toBe('all');
        expect(new URLSearchParams(agentQuery(0, false)).get('include_automated')).toBe('false');
        expect(new URLSearchParams(agentQuery(0, true)).get('include_automated')).toBe('true');
    });

    test('files archived projects apart from the rows and marks automated-only projects', async () => {
        const live = group({ name: 'live', key: '1', session_total: 1, counts: { running: 1 }, sessions: [session({ session_uuid: 'a', agent_family: 'claude', state: 'running' })] });
        const arch = group({ name: 'old', key: '2', session_total: 1, counts: { asleep: 1 }, sessions: [session({ session_uuid: 'b', agent_family: 'claude', state: 'asleep' })] });
        (arch.project as { id: number; archived_at: string | null }).id = 2;
        (arch.project as { archived_at: string | null }).archived_at = '2026-01-01';
        const bot = group({ name: 'bot', key: '3', session_total: 1, counts: { asleep: 1 }, automated_counts: { asleep: 1 }, sessions: [session({ session_uuid: 'c', agent_family: 'claude', state: 'asleep' })] });
        (bot.project as { id: number }).id = 3;
        const page: HistoryPage = { state: 'ok', total: 3, offset: 0, limit: 100, next_offset: null, groups: [live, arch, bot], facets: { agents: [], states: {} } };
        const list = vi.fn((_q: string) => Promise.resolve(page));
        const data = new SessionsData({ list } as unknown as HistoryApi, { records: () => Promise.resolve([]), counts: () => Promise.resolve({}) }, 'none', 'no datastore');
        data.setShowHidden(true);
        await vi.waitFor(() => expect(data.status).toBe('ready'));
        expect(list.mock.calls.at(-1)?.[0]).toContain('include_automated=true');
        expect(data.rows.map((r) => r.s.session_uuid).sort()).toEqual(['a', 'c']);
        expect(data.archivedProjects.map((p) => p.name)).toEqual(['old']);
        expect([...data.automatedProjectIds]).toEqual([3]);
    });
});

describe('bands, sort, search, archived band', () => {
    const groups = [lensGroup(proj(1, 'zeta'), 1, '2026-10-01T00:00:00Z'), lensGroup(proj(2, 'alpha'), 1, '2026-10-05T00:00:00Z'), lensGroup(proj(3, 'mango'), 0, '2026-09-01T00:00:00Z'), lensGroup(proj(4, 'bravo'), 0, '2026-09-20T00:00:00Z')];
    const labels = (g: { groups: readonly LensGroup[] }): string[] => g.groups.map((x) => x.label);

    test('sort: default keeps the lens order, name is a to z, last active is newest first', () => {
        expect(labels(projectBands(groups, [], '', true, 'default'))).toEqual(['zeta', 'alpha', 'bravo', 'mango']);
        expect(labels(projectBands(groups, [], '', true, 'name'))).toEqual(['alpha', 'zeta', 'bravo', 'mango']);
        expect(labels(projectBands(groups, [], '', true, 'recent'))).toEqual(['alpha', 'zeta', 'bravo', 'mango']);
        const flip = [lensGroup(proj(4, 'bravo'), 0, '2026-09-01T00:00:00Z'), lensGroup(proj(3, 'mango'), 0, '2026-09-20T00:00:00Z')];
        expect(labels(projectBands(flip, [], '', true, 'recent'))).toEqual(['mango', 'bravo']);
    });

    test('find matches an empty project by its company name', () => {
        const empties = [proj(5, 'quiet', { company_name: 'Acme Corp' }), proj(6, 'other', { company_name: 'Zed' })];
        expect(labels(projectBands([], empties, 'acme', true))).toEqual(['quiet']);
    });

    test('the archived band is heading-only, a to z, narrowed by name or company, empty while a filter is set', () => {
        const a = [proj(7, 'beta', { archived_at: 'x', company_name: 'Acme' }), proj(8, 'alpha', { archived_at: 'x' })];
        const band = archivedBand(a, '', true);
        expect(band.map((g) => g.label)).toEqual(['alpha', 'beta']);
        expect(band.every((g) => g.rows.length === 0)).toBe(true);
        expect(archivedBand(a, 'acme', true).map((g) => g.label)).toEqual(['beta']);
        expect(archivedBand(a, '', false)).toEqual([]);
    });
});

describe('remembered folds', () => {
    test('a choice writes the drawer fold list in one save and reads back', () => {
        storeFolds([['p:7', true], ['p:8', false]]);
        expect(folds.saves).toEqual([[['p:7', 'p:8:open'], ['p:7:open', 'p:8']]]);
        expect(storedFold('p:7')).toBe(true);
        expect(storedFold('p:8')).toBe(false);
        expect(storedFold('p:9')).toBeNull();
    });
});

describe('heading tags and the toggle', () => {
    function heading(project: Partial<HistoryProject>, onProjectAction = vi.fn(), extra: Record<string, unknown> = {}): HTMLElement {
        const g = { key: 'p:1', label: 'Shopify', bits: [], measure: '', rows: [], count: 0, live: 0, project: proj(1, 'Shopify', project), provider: null } as unknown as LensGroup;
        handle = mount(GroupSection, { target: document.body, props: { group: g, folded: false, t, onFold: vi.fn(), onProjectAction, children: createRawSnippet(() => ({ render: () => '<i></i>' })), ...extra } });
        flushSync();
        return document.querySelector<HTMLElement>('section.sp-sec')!;
    }

    test('a moved-away project says where it went and moves back with its button', () => {
        const act = vi.fn();
        const sec = heading({ pack_state: 'moved_away', moved_to_label: 'studio' }, act);
        expect(sec.querySelector('[data-tag="moved"]')?.textContent).toBe('moved to studio');
        sec.querySelector<HTMLButtonElement>('[data-move-back]')!.click();
        expect(act).toHaveBeenCalledWith('migrate-back', expect.anything());
    });

    test('an archived leaf heading tags itself, does not fold and an ordinary project has no tag', () => {
        const onFold = vi.fn();
        const sec = heading({ archived_at: '2026-01-01', storage: { state: 'packed', archive_bytes: 412000000 } as never }, vi.fn(), { leaf: true, onFold });
        expect(sec.querySelector('[data-tag="archived"]')).not.toBeNull();
        expect(sec.querySelector('[data-tag="pack"]')).not.toBeNull();
        expect(sec.hasAttribute('data-leaf')).toBe(true);
        sec.querySelector<HTMLButtonElement>('[data-fold]')!.click();
        expect(onFold).not.toHaveBeenCalled();
        unmount(handle!);
        document.body.innerHTML = '';
        const plain = heading({});
        expect(plain.querySelector('[data-tag]')).toBeNull();
        expect(plain.querySelector('[data-move-back]')).toBeNull();
    });

    test('the show-hidden toggle reports its state and flips', () => {
        const flip = vi.fn();
        handle = mount(TitleActions, { target: document.body, props: { onNewProject: vi.fn(), onNewCompany: vi.fn(), onNewSession: vi.fn(), showHidden: false, onToggleHidden: flip, showFold: false, allOpen: false, onToggleAll: vi.fn(), t } });
        flushSync();
        const b = document.querySelector<HTMLButtonElement>('[data-act="show-hidden"]')!;
        expect(b.getAttribute('aria-pressed')).toBe('false');
        b.click();
        expect(flip).toHaveBeenCalled();
    });
});

describe('the page', () => {
    test('lists archived projects in a collapsed archived fold under the active ones and opens it on press', async () => {
        const live = group({ name: 'live', key: '1', session_total: 1, counts: { running: 1 }, sessions: [session({ session_uuid: 'a', agent_family: 'claude', state: 'running', live_session_id: 'ses_1' })] });
        const arch = group({ name: 'old', key: '2' });
        (arch.project as { id: number }).id = 2;
        (arch.project as { archived_at: string | null }).archived_at = '2026-01-01';
        const page: HistoryPage = { state: 'ok', total: 2, offset: 0, limit: 100, next_offset: null, groups: [live, arch], facets: { agents: [], states: {} } };
        const api = { list: vi.fn(() => Promise.resolve(page)) } as unknown as HistoryApi;
        handle = mount(SessionsPage, { target: document.body, props: { api, readers: { records: () => Promise.resolve([]), counts: () => Promise.resolve({}) }, embedded: true, now: () => Date.UTC(2026, 9, 14) } });
        flushSync();
        await vi.waitFor(() => expect(document.querySelector('.sp-count')?.textContent).toBe('1 of 1'));
        expect(document.querySelector('[data-key="archived"]')).toBeNull();
        document.querySelector<HTMLButtonElement>('[data-state="archived"]')!.click();
        flushSync();
        await vi.waitFor(() => expect(document.querySelector('[data-key="archived"]')).not.toBeNull());
        const fold = document.querySelector<HTMLElement>('[data-key="archived"]')!;
        expect(fold.hasAttribute('data-folded')).toBe(true);
        expect(fold.hasAttribute('data-inactive')).toBe(true);
        expect(fold.querySelector('[data-key="project:archived:2"]')).toBeNull();
        fold.querySelector<HTMLButtonElement>('[data-fold]')!.click();
        flushSync();
        await vi.waitFor(() => expect(document.querySelector('[data-key="project:archived:2"] [data-tag="archived"]')).not.toBeNull());
        expect(folds.saves.at(-1)?.[0]).toEqual(['p:archived:open']);
    });
});
