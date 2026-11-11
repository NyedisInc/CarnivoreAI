import { expect, test } from 'vitest';
import { setLocale } from '../../i18n/index.svelte';
import { keysOfNodes } from '../../menu-keys/menu-keys';
import { entryNodes } from '../entries';
import { projectMenuEntries, type ProjectMenuInput } from './project-entries';

setLocale('en');

const input = (over: Partial<ProjectMenuInput> = {}): ProjectMenuInput => ({
    project: { id: 4, archived_at: null, root: '/a', company_id: 2, new_sessions_join_swarm: false },
    companies: [{ id: 2, name: 'Zed' }, { id: 1, name: 'Acme' }] as never,
    agentOffered: false,
    panels: [],
    color: { value: '', onPick: () => undefined },
    close: () => undefined,
    glyph: (icon) => (icon ? `<svg data-icon="${icon}"/>` : ''),
    run: () => undefined,
    ...over,
});
const nodesOf = (over?: Partial<ProjectMenuInput>) => {
    const i = input(over);
    return entryNodes(projectMenuEntries(i), i.glyph, i.close);
};

test('the drawer menu: ruled order, icons on every item, dividers, plain archive, danger delete, letters', () => {
    const nodes = nodesOf();
    expect(nodes.map((n) => n.id)).toEqual([
        'new-agent', 'load-blueprint', 'rename-project', 'pick-color', 'add-to-company', 'show-path',
        'sleep', 'swarm-new-sessions', 'migrate-project', 'project-settings', 'archive-project', 'delete-project',
    ]);
    expect(nodes.map((n) => n.label)).toEqual([
        'new agent', 'load blueprint', 'rename', 'color', 'company', 'show path', 'sleep',
        'new sessions join the swarm', 'move to pack member...', 'project settings', 'archive project', 'delete project',
    ]);
    expect(nodes.every((n) => n.glyphHtml), 'every item has an icon').toBe(true);
    expect(nodes.filter((n) => n.sep).map((n) => n.id)).toEqual(['rename-project', 'sleep', 'project-settings', 'archive-project']);
    const archive = nodes.find((n) => n.id === 'archive-project')!;
    expect(archive.danger).toBeUndefined();
    expect(archive.glyphHtml).toContain('archive');
    expect(nodes.find((n) => n.id === 'delete-project')!.danger).toBe(true);
    expect(nodes.find((n) => n.id === 'delete-project')!.glyphHtml).toContain('close');
    expect(keysOfNodes(nodes)).toEqual(['n', 'b', 'r', 'c', 'a', 'i', 's', 'e', 'm', 'p', 'v', 'd']);
    expect(nodes.find((n) => n.id === 'add-to-company')!.glyphHtml, 'the company item wears the company building').toContain('data-icon="company"');
});

test('no surface draws the fold item', () => {
    expect(nodesOf().map((n) => n.id)).not.toContain('fold-inside');
});

test('color opens a submenu holding the swatch row with its none swatch', () => {
    const color = nodesOf().find((n) => n.id === 'pick-color')!;
    expect(color.children).toHaveLength(1);
    expect(color.children![0]!.swatches).toMatchObject({ value: '', allowNone: true });
});

test('company is one submenu: every company, the current one in red, a rule, new company, remove from company', () => {
    const company = nodesOf().find((n) => n.id === 'add-to-company')!;
    expect(company.children!.map((c) => c.label)).toEqual(['Acme', 'Zed', 'new company', 'remove from company']);
    expect(company.children!.map((c) => c.danger === true)).toEqual([false, true, false, false]);
    expect(company.children!.map((c) => c.sep === true)).toEqual([false, false, true, false]);
    expect(new Set(keysOfNodes(company.children!)).size, 'no two letters alike').toBe(4);
    const unfiled = nodesOf({ project: { id: 4, archived_at: null, root: '/a', company_id: null } }).find((n) => n.id === 'add-to-company')!;
    expect(unfiled.children!.map((c) => c.label)).toEqual(['Acme', 'Zed', 'new company']);
});

test('a company pick and the leaves report their verbs; swarm shows its check', () => {
    const picked: string[] = [];
    const i = input({ run: (id) => picked.push(id), project: { id: 4, archived_at: null, root: '/a', company_id: null, new_sessions_join_swarm: true } });
    const nodes = entryNodes(projectMenuEntries(i), i.glyph, i.close);
    expect(nodes.find((n) => n.id === 'swarm-new-sessions')!.checked).toBe(true);
    nodes.find((n) => n.id === 'add-to-company')!.children![0]!.run!();
    nodes.find((n) => n.id === 'new-agent')!.run!();
    expect(picked).toEqual(['set-company:1', 'new-session']);
});
