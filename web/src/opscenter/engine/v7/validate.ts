
import { META, isInstanceId } from '../meta';
import { ROW_MAX } from '../model';
import { MAX_BYTES } from '../persist';
import { MAX_SPAN } from '../spans';
import type { LayoutPage, SlotId } from '../types';
import {
  MAX_AREA_DEPTH,
  MAX_SPLIT_CHILDREN,
  MAX_TREE_DEPTH,
  MAX_TREE_NODES,
  SCHEMA_VERSION_V7,
  SIZE_CLASSES,
  type LayoutNode,
  type LayoutV7,
  type SizeClass,
  type V7Check,
  type V7NodeCheck,
  type V7Refusal,
} from './types';

const SPLIT_ID = /^s[1-9][0-9]*$/;

export const FR_TOLERANCE = 1e-6;

export const MAX_PX_SIZE = ROW_MAX * MAX_SPAN;

const LAYOUT_FIELDS: ReadonlySet<string> = new Set(['v', 'variants', 'hidden', 'collapsed', 'heroCollapsed', 'headerOff']);
const VARIANT_FIELDS: ReadonlySet<string> = new Set(['root']);
const SPLIT_FIELDS: ReadonlySet<string> = new Set(['t', 'id', 'dir', 'sizes', 'unit', 'children']);
const LEAF_FIELDS: ReadonlySet<string> = new Set(['t', 'id']);

export type SlotIdCheck = (id: string) => boolean;

export const defaultIsSlotId: SlotIdCheck = (id) => id in META || isInstanceId(id as SlotId);

export interface NodeContext {
  page: LayoutPage;
  areaDepth?: number;
  isSlotId?: SlotIdCheck;
}

class Refused extends Error {
  constructor(
    readonly refusal: V7Refusal,
    detail: string,
  ) {
    super(detail);
  }
}

function refuse(refusal: V7Refusal, detail: string): never {
  throw new Refused(refusal, detail);
}

function record(value: unknown, refusal: V7Refusal, what: string): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) refuse(refusal, `${what} is not an object`);
  return value as Record<string, unknown>;
}

function onlyFields(value: Record<string, unknown>, known: ReadonlySet<string>, what: string): void {
  for (const key of Object.keys(value)) {
    if (!known.has(key)) refuse('unknown-field', `${what} carries an unknown field "${key}"`);
  }
}

function positive(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value > 0;
}

function checkTree(raw: unknown, context: NodeContext, seenLeaves: Set<string>): LayoutNode {
  const depthOfArea = context.areaDepth ?? 1;
  if (!Number.isInteger(depthOfArea) || depthOfArea < 1 || depthOfArea > MAX_AREA_DEPTH) {
    refuse('area-depth', `an area at depth ${depthOfArea} is outside 1 to ${MAX_AREA_DEPTH}`);
  }
  const isSlotId = context.isSlotId ?? defaultIsSlotId;
  const homeRoot = context.page === 'home' && depthOfArea === 1;
  const seenSplits = new Set<string>();
  let nodes = 0;

  const visit = (value: unknown, depth: number, isRoot: boolean, parentDir: string | null): LayoutNode => {
    nodes += 1;
    if (nodes > MAX_TREE_NODES) refuse('nodes', `the tree holds more than ${MAX_TREE_NODES} nodes`);
    if (depth > MAX_TREE_DEPTH) refuse('depth', `the tree is deeper than ${MAX_TREE_DEPTH}`);
    const node = record(value, 'node', 'a node');
    if (node['t'] === 'leaf') {
      onlyFields(node, LEAF_FIELDS, 'a leaf');
      const id = node['id'];
      if (typeof id !== 'string' || !isSlotId(id)) refuse('leaf-id', `leaf id ${JSON.stringify(id)} is not a slot id`);
      if (seenLeaves.has(id)) refuse('duplicate-leaf', `slot "${id}" appears twice`);
      seenLeaves.add(id);
      if (isRoot && homeRoot) refuse('home-root', 'the home root must be a vertical px split');
      return { t: 'leaf', id: id as SlotId };
    }
    if (node['t'] !== 'split') refuse('node', `node type ${JSON.stringify(node['t'])} is neither leaf nor split`);
    onlyFields(node, SPLIT_FIELDS, 'a split');
    const id = node['id'];
    if (typeof id !== 'string' || !SPLIT_ID.test(id)) refuse('split-id', `split id ${JSON.stringify(id)} is not s<number>`);
    if (seenSplits.has(id)) refuse('split-id', `split id "${id}" appears twice`);
    seenSplits.add(id);
    const dir = node['dir'];
    if (dir !== 'h' && dir !== 'v') refuse('dir', `split "${id}" has direction ${JSON.stringify(dir)}`);
    const unit = node['unit'];
    if (unit !== 'fr' && unit !== 'px') refuse('unit', `split "${id}" has unit ${JSON.stringify(unit)}`);
    const pixelRoot = isRoot && homeRoot;
    if (pixelRoot && (dir !== 'v' || unit !== 'px')) refuse('home-root', 'the home root must be a vertical px split');
    if (!pixelRoot && unit === 'px') refuse('unit', `split "${id}" is px, allowed only at the home root`);
    if (dir === parentDir) refuse('same-dir', `split "${id}" splits the same way as its parent`);

    const children = node['children'];
    if (!Array.isArray(children)) refuse('children', `split "${id}" has no children list`);
    const floor = pixelRoot ? 1 : 2;
    if (children.length < floor) {
      refuse(children.length === 1 ? 'single-child' : 'children', `split "${id}" holds ${children.length} children`);
    }
    if (children.length > MAX_SPLIT_CHILDREN) refuse('children', `split "${id}" holds more than ${MAX_SPLIT_CHILDREN}`);

    const sizes = node['sizes'];
    if (!Array.isArray(sizes) || sizes.length !== children.length) {
      refuse('sizes', `split "${id}" needs one size per child`);
    }
    if (!sizes.every(positive)) refuse('sizes', `split "${id}" has a size that is not a positive number`);
    if (unit === 'fr') {
      const total = (sizes as number[]).reduce((sum, one) => sum + one, 0);
      if (Math.abs(total - 1) > FR_TOLERANCE) refuse('sizes', `split "${id}" fr sizes sum to ${total}, not 1`);
    } else if ((sizes as number[]).some((one) => one > MAX_PX_SIZE)) {
      refuse('sizes', `split "${id}" has a px size above ${MAX_PX_SIZE}`);
    }
    const kids = (children as unknown[]).map((child) => visit(child, depth + 1, false, dir));
    return { t: 'split', id: id as `s${number}`, dir, unit, sizes: [...(sizes as number[])], children: kids };
  };

  return visit(raw, 1, true, null);
}

export function validateNode(raw: unknown, context: NodeContext): V7NodeCheck {
  try {
    return { ok: true, root: checkTree(raw, context, new Set()) };
  } catch (error) {
    if (error instanceof Refused) return { ok: false, refusal: error.refusal, detail: error.message };
    throw error;
  }
}

function slotList(raw: unknown, refusal: V7Refusal, what: string, isSlotId: SlotIdCheck): SlotId[] {
  if (!Array.isArray(raw)) refuse(refusal, `${what} is not a list`);
  const seen = new Set<string>();
  for (const id of raw as unknown[]) {
    if (typeof id !== 'string' || !isSlotId(id)) refuse(refusal, `${what} holds ${JSON.stringify(id)}`);
    if (seen.has(id)) refuse(refusal, `${what} holds "${id}" twice`);
    seen.add(id);
  }
  return [...(raw as SlotId[])];
}

export function validateV7(raw: unknown, page: LayoutPage, isSlotId: SlotIdCheck = defaultIsSlotId): V7Check {
  try {
    const blob = record(raw, 'malformed', 'the layout');
    if (blob['v'] !== SCHEMA_VERSION_V7) refuse('version', `version ${JSON.stringify(blob['v'])} is not 7`);
    onlyFields(blob, LAYOUT_FIELDS, 'the layout');
    if (JSON.stringify(raw).length > MAX_BYTES) refuse('oversize', `the layout is over ${MAX_BYTES} bytes`);
    const variants = record(blob['variants'], 'variants', 'variants');
    for (const key of Object.keys(variants)) {
      if (!(SIZE_CLASSES as readonly string[]).includes(key)) refuse('variants', `unknown size class "${key}"`);
    }
    const out = {} as Record<SizeClass, { root: LayoutNode }>;
    const onSurface = new Set<string>();
    for (const size of SIZE_CLASSES) {
      if (!(size in variants)) refuse('variants', `size class "${size}" is missing`);
      const variant = record(variants[size], 'variants', `variant "${size}"`);
      onlyFields(variant, VARIANT_FIELDS, `variant "${size}"`);
      const seen = new Set<string>();
      out[size] = { root: checkTree(variant['root'], { page, areaDepth: 1, isSlotId }, seen) };
      for (const id of seen) onSurface.add(id);
    }
    const hidden = slotList(blob['hidden'], 'hidden', 'hidden', isSlotId);
    const placed = hidden.find((id) => onSurface.has(id));
    if (placed) refuse('hidden', `"${placed}" is both hidden and on the surface`);
    const collapsed = slotList(blob['collapsed'], 'collapsed', 'collapsed', isSlotId);
    if (typeof blob['heroCollapsed'] !== 'boolean') refuse('hero-collapsed', 'heroCollapsed is not a boolean');
    const layout: LayoutV7 = { v: 7, variants: out, hidden, collapsed, heroCollapsed: blob['heroCollapsed'] };
    if (blob['headerOff'] !== undefined) layout.headerOff = slotList(blob['headerOff'], 'header-off', 'headerOff', isSlotId);
    return { ok: true, layout };
  } catch (error) {
    if (error instanceof Refused) return { ok: false, refusal: error.refusal, detail: error.message };
    throw error;
  }
}
