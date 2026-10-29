/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import { colorBook } from './agent-colors.svelte';
import { DEFAULT_PACK } from './characters';
import { buildFloor } from './floor';
import { lookOf, type NodeLooks } from './node-look';
import { nodeMenuTree } from './node-menu';
import type { PanelAgent } from './panel-state';
import SwarmPanel from './SwarmPanel.svelte';
import ChatAvatar from '../chat/ChatAvatar.svelte';
import type { BurstParty } from '../chat/chat-model';

const NOW = 1_000_000;
const BASE = { id: 4, display_name: 'Mimir', rank: 'feature', state: 'awake', thread_key: 'agent:4', session_id: 'ses_4', session_uuid: 'u-4', tmux_session: 'carnivore_mimir', project_id: 12 };
const OWN = { ...BASE, shape: 'hexagon', tile_bg: 3, color_slot: 5, color_chosen: true } as PanelAgent;
const PLACES = { companies: [{ id: 1, name: 'acme' }], projects: [{ id: 12, name: 'cloudecode', companyId: 1 }] };

const apps: object[] = [];
const proto = HTMLElement.prototype as unknown as Record<string, unknown>;
proto.showPopover ??= function () {};
proto.hidePopover ??= function () {};
afterEach(() => { for (const app of apps.splice(0)) unmount(app); document.body.innerHTML = ''; });

function face(el: Element | null): { shape: string | null; tile: string; body: string } {
  const ch = el?.querySelector('[data-state]') as HTMLElement | null;
  return { shape: ch?.getAttribute('data-shape') ?? null, tile: ch?.style.getPropertyValue('--tile') ?? '', body: ch?.style.getPropertyValue('--c') ?? '' };
}

function host(id: string): HTMLElement {
  const el = document.createElement('div');
  el.id = id;
  document.body.appendChild(el);
  return el;
}

function draw(agent: PanelAgent): { panel: HTMLElement; tile: ReturnType<typeof face>; avatar: ReturnType<typeof face> } {
  const roster = [agent];
  const floor = buildFloor({ agents: roster, sessions: [], ...PLACES, showInactive: true, rowOf: () => ({ activity_status: 'idle' }) as never });
  const book = colorBook(roster, { ...PLACES, sessions: [] });
  const looks: NodeLooks = { of: (ref) => lookOf(floor, book, ref, NOW), pack: DEFAULT_PACK };
  const panel = host('panel');
  apps.push(mount(SwarmPanel, { target: panel, props: {
    floor, agents: roster, density: 'expanded', now: NOW, colors: book, still: true, showInactive: true, onToggleInactive: vi.fn(), onOpen: vi.fn(),
  } }));
  const av = host('av');
  const party = { key: 'Mimir', dir: 'from', path: [], agentId: 4, sessionUuid: null, owner: false } as unknown as BurstParty;
  apps.push(mount(ChatAvatar, { target: av, props: { party, name: 'Mimir', looks } }));
  flushSync();
  return { panel, tile: face(panel.querySelector('[data-swarm-agent="4"]')), avatar: face(av) };
}

describe('the node menu', () => {
  test("a node's own shape, color and background draw identically on the drawer square and the chat avatar", () => {
    const own = draw(OWN);
    expect(own.tile).toEqual({ shape: 'hex', tile: 'color-mix(in oklch, var(--oc-series-3) 34%, transparent)', body: 'var(--oc-series-5)' });
    expect(own.avatar).toEqual(own.tile);
    document.body.innerHTML = '';
    const plain = draw(BASE as PanelAgent);
    expect(plain.tile.shape).toBe('sq');
    expect(plain.tile.tile).toBe('');
    expect(plain.tile.body).not.toBe('var(--oc-series-5)');
    expect(plain.avatar).toEqual(plain.tile);
  });

  test('a right-click on a square opens rename, color, background and shape with their hotkeys', () => {
    const { panel } = draw(OWN);
    const square = panel.querySelector('[data-swarm-agent="4"]') as HTMLElement;
    const event = new MouseEvent('contextmenu', { bubbles: true, cancelable: true });
    square.dispatchEvent(event);
    flushSync();
    expect(event.defaultPrevented).toBe(true);
    const items = [...document.querySelectorAll('[role="menu"] [role^="menuitem"]')] as HTMLElement[];
    expect(items.map((i) => [i.textContent?.replace(/\s+/g, ' ').trim(), i.dataset.menuKey])).toEqual([
      ['rename r', 'r'], ['color c', 'c'], ['background b', 'b'], ['shape s', 's'],
    ]);
  });

  test("each pick writes the agent's own look, and auto, none and tier default clear it", () => {
    const patch = vi.fn();
    const tree = nodeMenuTree(OWN, { rename: vi.fn(), patch });
    const pick = (branch: string, leaf: string) => tree.find((n) => n.id === branch)!.children!.find((n) => n.id === leaf)!;
    expect(pick('shape', 'shape-hexagon').checked).toBe(true);
    expect(pick('color', 'color-5').checked).toBe(true);
    expect(pick('background', 'background-3').checked).toBe(true);
    for (const [branch, leaf] of [['shape', 'shape-star'], ['shape', 'shape-default'], ['color', 'color-2'], ['color', 'color-auto'], ['background', 'background-7'], ['background', 'background-none']] as [string, string][]) pick(branch, leaf).run!();
    expect(patch.mock.calls.map((c) => c[0])).toEqual([
      { shape: 'star' }, { shape: null }, { color_slot: 2 }, { color_slot: null }, { tile_bg: 7 }, { tile_bg: null },
    ]);
  });
});
