import { authFetch, t, type MenuNode } from '../../sdk';
import { seriesVar, SERIES_COUNT } from './characters/look';
import { SHAPE_NAMES } from './characters/look-settings.svelte';
import { tileCss } from './node-look';
import type { PanelAgent } from './panel-state';

export interface LookPatch {
  color_slot?: number | null;
  shape?: string | null;
  tile_bg?: number | null;
}

export interface NodeMenuActions {
  rename(): void;
  patch(body: LookPatch): void;
}

export function swatchHtml(css: string): string {
  return `<span class="pk-swatch" style="background:${css}"></span>`;
}

const SLOTS = Array.from({ length: SERIES_COUNT }, (_, i) => i + 1);

export function nodeMenuTree(agent: PanelAgent, act: NodeMenuActions): MenuNode[] {
  const chosen = agent.color_chosen ? (agent.color_slot ?? null) : null;
  const bg = agent.tile_bg ?? null;
  const own = agent.shape && (SHAPE_NAMES as readonly string[]).includes(agent.shape) ? agent.shape : null;
  const slotLabel = (n: number) => t('cplug.huddle.swarm.node_menu.slot', { n });
  return [
    { id: 'rename', label: t('cplug.huddle.swarm.node_menu.rename'), run: () => act.rename() },
    {
      id: 'color', label: t('cplug.huddle.swarm.node_menu.color'), children: [
        { id: 'color-auto', label: t('cplug.huddle.swarm.node_menu.auto'), checked: chosen === null, run: () => act.patch({ color_slot: null }) },
        ...SLOTS.map((n) => ({ id: `color-${n}`, label: slotLabel(n), checked: chosen === n, aggregateLightHtml: swatchHtml(seriesVar(n)), run: () => act.patch({ color_slot: n }) })),
      ],
    },
    {
      id: 'background', label: t('cplug.huddle.swarm.node_menu.background'), children: [
        { id: 'background-none', label: t('cplug.huddle.swarm.node_menu.none'), checked: bg === null, run: () => act.patch({ tile_bg: null }) },
        ...SLOTS.map((n) => ({ id: `background-${n}`, label: slotLabel(n), checked: bg === n, aggregateLightHtml: swatchHtml(tileCss(n) ?? ''), run: () => act.patch({ tile_bg: n }) })),
      ],
    },
    {
      id: 'shape', label: t('cplug.huddle.swarm.node_menu.shape'), children: [
        { id: 'shape-default', label: t('cplug.huddle.swarm.node_menu.tier_default'), checked: own === null, run: () => act.patch({ shape: null }) },
        ...SHAPE_NAMES.map((name) => ({ id: `shape-${name}`, label: t(`cplug.huddle.swarm.settings.look.shape.${name}`), checked: own === name, run: () => act.patch({ shape: name }) })),
      ],
    },
  ];
}

export async function patchLook(id: number, body: LookPatch): Promise<void> {
  await authFetch(`/swarm/agents/${id}`, { method: 'PATCH', body: JSON.stringify(body) });
}

export const HOLD_MS = 500;
export const HOLD_SLOP_PX = 8;

export function nodeHold(node: HTMLElement, onHold: (node: HTMLElement) => void): { update(next: (node: HTMLElement) => void): void; destroy(): void } {
  let hold = onHold;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let start: { x: number; y: number } | null = null;
  const stop = () => { if (timer) clearTimeout(timer); timer = null; start = null; };
  const down = (e: PointerEvent) => {
    if (e.pointerType !== 'touch') return;
    start = { x: e.clientX, y: e.clientY };
    timer = setTimeout(() => { stop(); hold(node); }, HOLD_MS);
  };
  const move = (e: PointerEvent) => {
    if (start && Math.hypot(e.clientX - start.x, e.clientY - start.y) > HOLD_SLOP_PX) stop();
  };
  node.addEventListener('pointerdown', down);
  node.addEventListener('pointermove', move);
  node.addEventListener('pointerup', stop);
  node.addEventListener('pointercancel', stop);
  return {
    update(next) { hold = next; },
    destroy() {
      stop();
      node.removeEventListener('pointerdown', down);
      node.removeEventListener('pointermove', move);
      node.removeEventListener('pointerup', stop);
      node.removeEventListener('pointercancel', stop);
    },
  };
}
