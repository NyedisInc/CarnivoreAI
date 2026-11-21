/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const puts: Array<Record<string, unknown>> = [];
vi.mock('../../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../../opscenter/api/auth.svelte')>();
  const { AGENTS } = await import('../style-guide/swarm-fixture');
  return {
    ...real,
    authFetch: async (path: string, init?: { method?: string; body?: string }) => {
      if (path === '/swarm/roster') return { agents: AGENTS, threads_ready: true };
      if (path === '/swarm/settings') {
        if (init?.method === 'PUT') puts.push(JSON.parse(init.body ?? '{}'));
        return { page_default_view: 'tree', panel_default_density: 'expanded', character_pack: 'theme', ...Object.assign({}, ...puts) };
      }
      return {};
    },
  };
});
vi.mock('../../sdk', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../sdk')>();
  const fx = await import('../style-guide/swarm-fixture');
  return {
    ...real,
    floorSource: () => ({ sessions: fx.SESSIONS, companies: fx.COMPANIES, projects: fx.PROJECTS }),
    sessionRow: (id: string | null) => fx.rowOf(id),
  };
});

import { setLocale } from '../../../lib/i18n/index.svelte';
import { menuPage } from '../../../lib/menu-page/menu-pages';
import SwarmPage from '../../../lib/huddle-swarm/SwarmPage.svelte';
import HuddleSwarmSettings from '../../../lib/plugins-page/HuddleSwarmSettings.svelte';
import { AGENTS, COMPANIES, NOW, PROJECTS, SESSIONS, rowOf } from '../style-guide/swarm-fixture';
import { buildFloor } from './floor';
import ledgerSource from './SwarmLedger.svelte?raw';
import { layoutOrg, clampZoom, fitView, zoomAt, ZOOM_MAX, ZOOM_MIN } from './org-layout';
import { lineageFloor } from './floor';
import { agentPage } from '../agents/agent-page.svelte';
import { mk } from '../style-guide/swarm-fixture';
import { buildTree, floorItems, ledgerRows } from './swarm-tree';
import { swarmInactive } from '../huddle-swarm-inactive.svelte';

setLocale('en');

const floor = () => buildFloor({ agents: AGENTS, sessions: SESSIONS, companies: COMPANIES, projects: PROJECTS, rowOf, showInactive: false });

describe('the tree', () => {
  test('rows nest by parent: projects under companies, agents under their parent, sessions under their project', () => {
    const tree = buildTree(floor());
    const parent = (key: string) => tree.nodes.get(key)?.parent;
    expect(tree.roots).toEqual(['agent:1']);
    expect(parent('agent:4')).toBe('agent:1');
    expect(parent('agent:5')).toBe('agent:4');
    expect(parent('agent:10')).toBe('agent:5');
    expect(parent('session:web')).toBe('agent:8');
    expect(parent('project:6')).toBe('agent:1');
    const depths = tree.order.map((key) => tree.nodes.get(key)?.depth ?? -1);
    expect(depths[0]).toBe(0);
    expect(tree.nodes.get('agent:10')!.depth).toBe(tree.nodes.get('agent:5')!.depth + 1);
  });

  test('collapsing a node hides what is under it, and every floor item is a node', () => {
    const tree = buildTree(floor());
    expect(tree.order).toHaveLength(floorItems(floor()).length);
    const all = ledgerRows(tree, new Set()).map((n) => n.item.key);
    const folded = ledgerRows(tree, new Set(['agent:5'])).map((n) => n.item.key);
    expect(all).toContain('agent:10');
    expect(folded).not.toContain('agent:10');
    expect(folded).toContain('agent:5');
  });
});

describe('the org chart layout and zoom', () => {
  test('one link per non-root node, every node placed', () => {
    const tree = buildTree(buildFloor({ agents: AGENTS, sessions: SESSIONS.filter((s) => s.key !== 'nap'), companies: COMPANIES, projects: PROJECTS, rowOf, showInactive: false }));
    const layout = layoutOrg(tree);
    expect(layout.links).toHaveLength(tree.order.length - tree.roots.length);
    expect(new Set(layout.links.map((l) => l.to)).size).toBe(layout.links.length);
    expect(layout.nodes.every((n) => Number.isFinite(n.x) && Number.isFinite(n.y))).toBe(true);
    const view = fitView(layout, 1098, 600);
    expect(view.x + Math.max(...layout.nodes.map((n) => n.x + n.w / 2)) * view.k).toBeLessThanOrEqual(1098);
  });

  test('a population wider than the panel wraps its sibling rows: first paint at scale 1, nothing past the right edge', () => {
    const tree = buildTree(floor());
    expect(layoutOrg(tree).width).toBeGreaterThan(700);
    const layout = layoutOrg(tree, 700);
    const view = fitView(layout, 700, 600);
    expect(view.k).toBe(1);
    expect(view.x + Math.max(...layout.nodes.map((n) => n.x + n.w / 2))).toBeLessThanOrEqual(700);
    expect(Math.min(...layout.nodes.map((n) => n.x - n.w / 2))).toBeGreaterThanOrEqual(0);
    const top = layout.nodes.filter((n) => tree.nodes.get(n.key)?.parent === 'agent:1' && !n.stacked);
    expect(new Set(top.map((n) => n.y)).size).toBeGreaterThan(1);
    expect(layout.links).toHaveLength(tree.order.length - tree.roots.length);
  });

  test('SysOp hangs its own leaves off its trunk, above every company, and every connector path draws', () => {
    const tree = buildTree(floor());
    for (const panel of [Number.POSITIVE_INFINITY, 1098, 700]) {
      const layout = layoutOrg(tree, panel);
      const at = (key: string) => layout.nodes.find((n) => n.key === key)!;
      const sysop = at('agent:1');
      const companies = layout.nodes.filter((n) => tree.nodes.get(n.key)?.item.rank === 'company');
      const leaves = ['agent:12', 'agent:13', 'agent:14'].map(at);
      for (const leaf of leaves) {
        expect(leaf.x - leaf.w / 2).toBeGreaterThan(sysop.x);
        expect(leaf.y - leaf.h / 2).toBeGreaterThan(sysop.y + sysop.h / 2);
        for (const c of companies) expect(leaf.y + leaf.h / 2).toBeLessThan(c.y - c.h / 2);
      }
      expect(layout.links.filter((l) => !l.d.split(/[\s,]+/).every((t) => /^[MVHLC]$/.test(t) || Number.isFinite(Number(t))))).toEqual([]);
    }
  });

  test('org nodes never overlap on a level and a link runs edge to edge, never through a node', () => {
    const tree = buildTree(floor());
    const layout = layoutOrg(tree);
    const byY = new Map<number, typeof layout.nodes>();
    for (const n of layout.nodes) byY.set(n.y, [...(byY.get(n.y) ?? []), n]);
    for (const level of byY.values()) {
      const sorted = [...level].sort((a, b) => a.x - b.x);
      for (let i = 1; i < sorted.length; i += 1) expect(sorted[i]!.x - sorted[i]!.w / 2).toBeGreaterThanOrEqual(sorted[i - 1]!.x + sorted[i - 1]!.w / 2);
    }
    for (const link of layout.links) {
      const a = layout.nodes.find((n) => n.key === link.from)!;
      const b = layout.nodes.find((n) => n.key === link.to)!;
      expect(link.d.startsWith(`M ${a.x} ${a.y + a.h / 2} `)).toBe(true);
      expect(link.d.endsWith(b.stacked ? `${b.x - b.w / 2} ${b.y}` : `${b.x} ${b.y - b.h / 2}`)).toBe(true);
    }
  });

  test('zoom stays inside its bounds however far it is pushed', () => {
    let view = { x: 0, y: 0, k: 1 };
    for (let i = 0; i < 60; i += 1) view = zoomAt(view, 1.2, 100, 80);
    expect(view.k).toBe(ZOOM_MAX);
    for (let i = 0; i < 120; i += 1) view = zoomAt(view, 1 / 1.2, 100, 80);
    expect(view.k).toBe(ZOOM_MIN);
    expect(clampZoom(Number.NaN)).toBe(1);
    expect(clampZoom(99)).toBe(ZOOM_MAX);
  });
});

describe('the page', () => {
  let app: object | null = null;
  const host = (): HTMLElement => document.body.firstElementChild as HTMLElement;

  beforeEach(() => {
    puts.length = 0;
    localStorage.clear();
    swarmInactive.shown = false;
    vi.spyOn(Date, 'now').mockReturnValue(NOW);
    document.body.innerHTML = '<div id="t"></div>';
    app = mount(SwarmPage, { target: document.getElementById('t') as HTMLElement, props: { embedded: true } });
  });
  afterEach(() => {
    if (app) unmount(app);
    app = null;
    vi.restoreAllMocks();
  });

  async function settle(): Promise<void> {
    for (let i = 0; i < 4; i += 1) {
      await new Promise((resolve) => setTimeout(resolve, 0));
      await tick();
      flushSync();
    }
  }
  const tab = (id: string): HTMLButtonElement => host().querySelector(`#swarm-tab-${id}`) as HTMLButtonElement;

  test('opens on the ledger and draws every tree row with its depth', async () => {
    await settle();
    expect(host().querySelector('[data-swarm-page]')?.getAttribute('data-swarm-tab')).toBe('tree');
    const rows = [...host().querySelectorAll('[data-swarm-row]')];
    expect(rows.length).toBeGreaterThan(10);
    const depth = (key: string) => Number(host().querySelector(`[data-swarm-row="${key}"]`)?.getAttribute('data-swarm-depth'));
    expect(depth('agent:10')).toBeGreaterThan(depth('agent:5'));
    expect(host().querySelector('[data-swarm-row="agent:1"] [data-swarm-fold]')).not.toBeNull();
  });

  test('the ledger indents only the name cell: every other column is a direct cell of one grid at every depth', async () => {
    await settle();
    const rows = [...host().querySelectorAll('[data-swarm-row]')] as HTMLElement[];
    const depths = new Set(rows.map((r) => r.getAttribute('data-swarm-depth')));
    expect(depths.size).toBeGreaterThan(2);
    for (const row of rows) {
      const cells = [...(row.querySelector('.pkg-main') as HTMLElement).children].map((c) => c.className.split(' ')[0]);
      expect(cells).toEqual(['pkg-who', 'pkg-rank', 'pkg-state', 'pkg-job', 'pkg-effort', 'pkg-alert']);
    }
    expect(host().querySelectorAll('.pkg-head > span')).toHaveLength(6);
    const css = ledgerSource.match(/\.pkg-row \{[^}]*\}/)?.[0] ?? '';
    expect(css).not.toMatch(/padding/);
    expect(ledgerSource.match(/\.pkg-who \{[^}]*\}/)?.[0]).toMatch(/padding-left: calc\(var\(--pkg-depth\)/);
  });

  test('the org chart has one link per non-root node, and squares use the expanded panel', async () => {
    await settle();
    const nodes = host().querySelectorAll('[data-swarm-row]').length;
    tab('org').click();
    await settle();
    expect(host().querySelectorAll('[data-swarm-node]')).toHaveLength(nodes);
    expect(host().querySelectorAll('path[data-swarm-link]')).toHaveLength(nodes - 1);
    const zoomIn = host().querySelector('[data-swarm-zoom-in]') as HTMLButtonElement;
    for (let i = 0; i < 40; i += 1) zoomIn.click();
    await settle();
    expect(Number(host().querySelector('[data-swarm-org]')?.getAttribute('data-swarm-zoom'))).toBeLessThanOrEqual(ZOOM_MAX);
    tab('squares').click();
    await settle();
    expect(host().querySelector('[data-swarm-panel]')?.getAttribute('data-density')).toBe('expanded');
  });

  test('the org chart stacks leaf agents so the 2026-10-07 population fits at 1440, and every page view draws the selected node lineage', async () => {
    const names = ['Cv-PageUIRedesign', 'Cv-SwarmChats', 'Cv-FixSettings', 'Cv-Layer1', 'Drawer Agents Tab Grey Hairline Grouping Headings',
      'Reset The Drawer Swarm Panel Filter When Hidden', 'Fix The Questions Tab Card Drops The Opening Lines', 'Full Swarm Page Views Use The Node Filter'];
    const agents = [
      mk(1, 'SysOp', 'alpha', { thread_key: 'all' }), mk(2, 'Acme agent', 'company', { company_id: 1 }),
      mk(3, 'Cobalt agent', 'project', { project_id: 10 }), mk(4, 'Cobalt agent', 'project', { project_id: 11 }),
      mk(5, 'Carnivore.ai agent', 'project', { project_id: 12 }),
      mk(31, 'ASI-Connectors', 'task', { parent_id: 3 }), mk(32, 'ASI-Deploy', 'task', { parent_id: 3 }), mk(41, 'Argent-DocsCodex', 'task', { parent_id: 4 }),
      ...names.map((n, i) => mk(51 + i, n, 'task', { parent_id: 5 })),
    ];
    const shot = buildFloor({ agents, sessions: [], companies: [{ id: 1, name: 'Nyedis' }],
      projects: [{ id: 10, name: 'Cobalt', companyId: 1 }, { id: 11, name: 'Argent', companyId: 1 }, { id: 12, name: 'Carnivore.ai', companyId: 1 }],
      rowOf: () => undefined, showInactive: true });
    const org = layoutOrg(buildTree(shot));
    const at = (key: string) => org.nodes.find((n) => n.key === key)!;
    expect(org.width).toBeLessThanOrEqual(1440 - 64);
    expect(fitView(org, 1440 - 64, 600).k).toBeGreaterThanOrEqual(1);
    const carnivore = names.map((_, i) => at(`agent:${51 + i}`));
    expect(carnivore.every((n) => n.stacked)).toBe(true);
    expect(new Set(carnivore.map((n) => n.x)).size).toBe(2);
    expect(new Set(carnivore.map((n) => n.y)).size).toBe(4);
    expect(at('agent:31').x).toBe(at('agent:32').x);
    expect(at('agent:32').y).toBeGreaterThan(at('agent:31').y);
    expect(at('agent:5').stacked).toBe(false);
    expect(new Set([at('agent:3').y, at('agent:4').y, at('agent:5').y]).size).toBe(1);

    agentPage.id = 5;
    try {
      await settle();
      tab('org').click();
      await settle();
      const nodes = (): string[] => [...host().querySelectorAll('[data-swarm-node]')].map((n) => n.getAttribute('data-swarm-node') as string);
      const scoped = buildTree(lineageFloor(floor(), 'agent:5')).order;
      expect(scoped.length).toBeLessThan(buildTree(floor()).order.length);
      expect(nodes()).toEqual(scoped);
      const five = (): HTMLElement => host().querySelector('[data-swarm-node="agent:5"]') as HTMLElement;
      expect(five().getAttribute('aria-current')).toBe('true');
      five().dispatchEvent(new MouseEvent('click', { bubbles: true, shiftKey: true }));
      await settle();
      expect(agentPage.id).toBe(null);
      expect(nodes()).toEqual(buildTree(floor()).order);
      five().dispatchEvent(new MouseEvent('click', { bubbles: true, shiftKey: true }));
      await settle();
      expect(nodes()).toEqual(scoped);
    } finally {
      agentPage.id = null;
      agentPage.node = null;
    }
  });

  test('the plugin pane is the one settings home: it holds the look and the page fields, and the Swarm page has no settings tab', async () => {
    await settle();
    expect(tab('settings')).toBeNull();
    expect(host().querySelector('[data-swarm-settings]')).toBeNull();
    const menu = document.createElement('div');
    document.body.appendChild(menu);
    const screen = mount(HuddleSwarmSettings, { target: menu });
    try {
      await settle();
      for (const id of ['color_mode', 'shape-sysop', 'shape-agent', 'animation-working', 'page_default_view', 'panel_default_density', 'closeout_window_minutes', 'max_children_per_parent', 'max_live_bodies', 'spawn_load_per_core']) {
        expect(menu.querySelector(`#swarm-setting-${id}`), id).not.toBeNull();
      }
      expect(menu.querySelectorAll('[data-swarm-look-preview]').length).toBeGreaterThan(4);
      const pick = async (row: string, value: string): Promise<void> => {
        const field = menu.querySelector(`#swarm-setting-${row}`) as HTMLSelectElement | HTMLInputElement;
        field.value = value;
        field.dispatchEvent(new Event('change', { bubbles: true }));
        await settle();
      };
      await pick('page_default_view', 'squares');
      await pick('color_mode', 'random');
      await pick('closeout_window_minutes', '30');
      await pick('closeout_window_minutes', '0');
      expect((menu.querySelector('#swarm-setting-max_live_bodies') as HTMLInputElement).value).toBe('');
      await pick('max_live_bodies', '40');
      await pick('max_live_bodies', '2.5');
      await pick('max_live_bodies', '');
      await pick('spawn_load_per_core', '3.5');
      expect(puts).toEqual([{ page_default_view: 'squares' }, { color_mode: 'random' }, { closeout_window_minutes: 30 },
        { max_live_bodies: 40 }, { max_live_bodies: null }, { spawn_load_per_core: 3.5 }]);
    } finally {
      unmount(screen);
      menu.remove();
    }
  });
});

describe('the menu page', () => {
  test('is `huddle-swarm` at #swarm and keeps the drawer on its tab', () => {
    const page = menuPage('huddle-swarm');
    expect(page?.hashes).toEqual(['#swarm']);
    expect(page?.keepDrawerTab).toBe(true);
    expect(page?.containerId).toBe('huddle-swarm-screen');
  });
});
