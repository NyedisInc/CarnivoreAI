import type { AgentColor, CharacterPack } from './characters';
import { homeShapeOf } from './characters/look-settings.svelte';
import { HOME_SHAPES, type HomeShape, type HomeShapeName } from './characters/shapes';
import type { Tell } from './characters/states';
import type { ColorBook } from './agent-colors.svelte';
import type { Floor, FloorItem } from './floor';
import { seedOf, squareState, sendOf, type PanelAgent } from './panel-state';

export interface NodeRef {
  agentId?: number | null;
  sessionUuid?: string | null;
}

export function floorItems(floor: Floor): FloorItem[] {
  return [...(floor.alpha ? [floor.alpha] : []), ...floor.companies, ...floor.projects, ...floor.agents];
}

export function findNode(floor: Floor, ref: NodeRef): FloorItem | null {
  const items = floorItems(floor).filter((i) => !i.vacant && i.agent);
  if (typeof ref.agentId === 'number') {
    const hit = items.find((i) => !i.ordinary && i.agent?.id === ref.agentId);
    if (hit) return hit;
  }
  const uuid = ref.sessionUuid;
  if (!uuid) return null;
  return items.find((i) => i.session?.sessionUuid === uuid || (!i.ordinary && i.agent?.session_uuid === uuid)) ?? null;
}

export function colorFor(book: ColorBook, item: FloorItem): AgentColor | null {
  return item.agent ? book.of(item.agent) : null;
}

export function stateFor(item: FloorItem, nowMs: number): string {
  return item.agent ? squareState(item.agent, item.row, nowMs, item.rollup) : 'vacant';
}

export function shapeFor(item: FloorItem): HomeShape {
  const own = item.ordinary ? null : item.agent?.shape;
  return own && own in HOME_SHAPES ? HOME_SHAPES[own as HomeShapeName] : homeShapeOf(item.agent?.rank ?? item.rank);
}

export function backgroundFor(item: FloorItem): string | null {
  return tileCss(item.ordinary ? null : item.agent?.tile_bg);
}

export function tileCss(slot: number | null | undefined): string | null {
  return typeof slot === 'number' && slot >= 1 && slot <= 8 ? `color-mix(in oklch, var(--oc-series-${slot}) 34%, transparent)` : null;
}

export function sendFor(item: FloorItem): Tell | null {
  return item.agent ? sendOf(item.agent, item.row) : null;
}

export function markRankOf(item: FloorItem): string | null {
  return item.ordinary || !item.agent ? null : item.agent.rank ?? null;
}

export interface NodeLook {
  item: FloorItem;
  agent: PanelAgent;
  color: AgentColor | null;
  state: string;
  shape: HomeShape;
  background: string | null;
  tell: Tell | null;
  seed: number;
}

export function lookOf(floor: Floor, book: ColorBook, ref: NodeRef, nowMs: number): NodeLook | null {
  const item = findNode(floor, ref);
  if (!item?.agent) return null;
  return { item, agent: item.agent, color: colorFor(book, item), state: stateFor(item, nowMs), shape: shapeFor(item), background: backgroundFor(item), tell: sendFor(item), seed: seedOf(item.agent) };
}

export interface NodeLooks {
  of(ref: NodeRef): NodeLook | null;
  readonly pack: CharacterPack;
}
