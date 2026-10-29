
import type { SlotId } from '../types';

export const SCHEMA_VERSION_V7 = 7;

export type SplitDir = 'h' | 'v';

export type SizeUnit = 'fr' | 'px';

export type SplitId = `s${number}`;

export interface SplitNode {
  t: 'split';
  id: SplitId;
  dir: SplitDir;
  sizes: number[];
  unit: SizeUnit;
  children: LayoutNode[];
}

export interface LeafNode {
  t: 'leaf';
  id: SlotId;
}

export type LayoutNode = SplitNode | LeafNode;

export type SizeClass = 'wide';

export const SIZE_CLASSES: readonly SizeClass[] = ['wide'];

export interface LayoutVariant {
  root: LayoutNode;
}

export interface LayoutV7 {
  v: 7;
  variants: Record<SizeClass, LayoutVariant>;
  hidden: SlotId[];
  collapsed: SlotId[];
  heroCollapsed: boolean;
  headerOff?: SlotId[];
}

export const MAX_AREA_DEPTH = 2;

export const MAX_TREE_DEPTH = 16;

export const MAX_TREE_NODES = 256;

export const MAX_SPLIT_CHILDREN = 64;

export type V7Refusal =
  | 'malformed'
  | 'unknown-field'
  | 'version'
  | 'variants'
  | 'oversize'
  | 'node'
  | 'split-id'
  | 'leaf-id'
  | 'duplicate-leaf'
  | 'dir'
  | 'unit'
  | 'sizes'
  | 'children'
  | 'single-child'
  | 'same-dir'
  | 'home-root'
  | 'depth'
  | 'nodes'
  | 'area-depth'
  | 'hidden'
  | 'collapsed'
  | 'hero-collapsed'
  | 'header-off';

export type V7Check =
  | { ok: true; layout: LayoutV7 }
  | { ok: false; refusal: V7Refusal; detail: string };

export type V7NodeCheck =
  | { ok: true; root: LayoutNode }
  | { ok: false; refusal: V7Refusal; detail: string };
