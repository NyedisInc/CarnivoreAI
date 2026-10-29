import type { BoardPrompt, BoardRevision, BoardSidecar } from './board-model';
import type { GapLayout } from './bridge-host';
import type { Draft } from './tray-model';

export interface InlineProps {
  sidecar: BoardSidecar;
  prompts: BoardPrompt[];
  draft: Draft | null;
  revisionId: string;
  revisionN: number;
  onedit: (change: (draft: Draft | null) => Draft | null) => void;
  onplaced: (ids: string[]) => void;
}

export const GAP_MARGIN = 6;
const ESTIMATE: Record<BoardPrompt['kind'], number> = { choice: 64, multi: 64, check: 40, question: 80 };

export function inlinePrompts(revision: Pick<BoardRevision, 'inline_picks' | 'anchors' | 'prompts'> | null, enabled: boolean): BoardPrompt[] {
  if (!revision || !revision.inline_picks || !enabled) return [];
  const declared = new Set(revision.anchors.map((a) => a.id));
  return revision.prompts.filter((p) => !!p.anchor && declared.has(p.anchor));
}

export function groupByAnchor(prompts: readonly BoardPrompt[]): Array<[string, BoardPrompt[]]> {
  const groups = new Map<string, BoardPrompt[]>();
  for (const p of prompts) if (p.anchor) groups.set(p.anchor, [...(groups.get(p.anchor) ?? []), p]);
  return [...groups.entries()];
}

export function estimateRooms(prompts: readonly BoardPrompt[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const [anchor, group] of groupByAnchor(prompts)) out[anchor] = group.reduce((sum, p) => sum + ESTIMATE[p.kind], 0) + GAP_MARGIN;
  return out;
}

export function roomsFromHeights(heights: Readonly<Record<string, number>>, scale: number): Record<string, number> {
  const out: Record<string, number> = {};
  const s = scale > 0 ? scale : 1;
  for (const [anchor, h] of Object.entries(heights)) if (Number.isFinite(h) && h > 0) out[anchor] = Math.ceil(h / s) + GAP_MARGIN;
  return out;
}

export function sameRooms(a: Readonly<Record<string, number>>, b: Readonly<Record<string, number>>): boolean {
  const keys = Object.keys(a);
  return keys.length === Object.keys(b).length && keys.every((k) => a[k] === b[k]);
}

export interface PlacedBlock { anchor: string; prompts: BoardPrompt[]; left: number; top: number; width: number }

export function placeBlocks(prompts: readonly BoardPrompt[], spots: GapLayout, scale: number): PlacedBlock[] {
  const s = scale > 0 ? scale : 1;
  const placed: PlacedBlock[] = [];
  for (const [anchor, group] of groupByAnchor(prompts)) {
    const spot = spots[anchor];
    if (spot) placed.push({ anchor, prompts: group, left: spot.x * s, top: spot.y * s, width: Math.max(0, spot.w * s) });
  }
  return placed;
}
