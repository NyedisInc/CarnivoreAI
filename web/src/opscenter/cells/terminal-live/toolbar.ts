/* keep awake */

import { pickState, atLeast } from '../../lib/states';
import type { CellSize } from '../../engine/types';
import type { TerminalAction } from './actions';
import { showsStatusLight } from '../../../lib/sessions/agent-marks';

export const TOOLBAR_STEPS: readonly CellSize[] = [
  { name: 'none', min: 0 },
  { name: 'search', min: 260 },
  { name: 'files', min: 300 },
  { name: 'notes', min: 340 },
  { name: 'sleep', min: 380 },
  { name: 'theme', min: 420 },
  { name: 'size-master', min: 460 },
  { name: 'utilities', min: 500 },
  { name: 'skills', min: 540 },
  { name: 'plugins', min: 580 },
  { name: 'background', min: 620 },
];

export interface ToolbarItem {
  id: string;
  action: TerminalAction | null;
  icon: string | null;
  label: string | null;
  from: string;
}

/* nothing at all */
export const TOOLBAR_ITEMS: readonly ToolbarItem[] = [
  { id: 'skills', action: 'skills', icon: 'skill', label: 'terminal.strip.skills', from: 'skills' },
  { id: 'plugins', action: 'plugins', icon: 'cube', label: 'terminal.strip.plugins', from: 'plugins' },
  { id: 'files', action: 'files', icon: 'folder', label: 'terminal.strip.files', from: 'files' },
  { id: 'search', action: 'search', icon: 'search', label: 'terminal.strip.search', from: 'search' },
  { id: 'notes', action: null, icon: 'docs', label: 'terminal.strip.notes', from: 'notes' },
  { id: 'theme', action: null, icon: 'palette', label: 'terminal.strip.theme', from: 'theme' },
  { id: 'background', action: null, icon: null, label: null, from: 'background' },
  { id: 'utilities', action: null, icon: null, label: null, from: 'utilities' },
  { id: 'sleep', action: null, icon: 'moon', label: 'opscenter.tabs.sleep', from: 'sleep' },
  { id: 'size-master', action: null, icon: 'crown', label: 'terminal.strip.size_master', from: 'size-master' },
];

export const MENU_HOME: ReadonlySet<string> = new Set(['skills', 'plugins', 'files', 'notes', 'theme', 'background']);

/* keep awake */
export const AGENT_ONLY: ReadonlySet<string> = new Set(['skills', 'plugins']);

export function itemApplies(id: string, family: string | null | undefined): boolean {
  return !AGENT_ONLY.has(id) || showsStatusLight(family);
}

export const STRIP_ITEMS: readonly ToolbarItem[] = TOOLBAR_ITEMS.filter((item) => !MENU_HOME.has(item.id));

export function menuItems(folded: ReadonlySet<string>): ToolbarItem[] {
  return TOOLBAR_ITEMS.filter((item) => MENU_HOME.has(item.id) || folded.has(item.id));
}

export interface ToolbarSplit {
  state: string;
  bar: readonly ToolbarItem[];
  overflow: readonly ToolbarItem[];
}

export function splitToolbar(width: number, previous?: string): ToolbarSplit {
  const state = pickState(TOOLBAR_STEPS, width, previous);
  const bar = STRIP_ITEMS.filter((item) => atLeast(TOOLBAR_STEPS, state, item.from));
  return { state, bar, overflow: menuItems(new Set(STRIP_ITEMS.filter((item) => !bar.includes(item)).map((item) => item.id))) };
}

export interface FoldCandidate {
  id: string;
  width: number;
  active: boolean;
}

export function planFolds(room: number, kebab: number, items: readonly FoldCandidate[]): string[] {
  const rank = new Map(TOOLBAR_ITEMS.map((item, i) => [
    item.id, TOOLBAR_STEPS.findIndex((s) => s.name === item.from) * 100 + i]));
  const byDrop = (a: FoldCandidate, b: FoldCandidate): number => (rank.get(b.id) ?? 0) - (rank.get(a.id) ?? 0);
  let total = kebab + items.reduce((sum, item) => sum + item.width, 0);
  const folded: string[] = [];
  for (const wantActive of [false, true]) {
    for (const item of items.filter((i) => i.active === wantActive && i.width > 0).sort(byDrop)) {
      if (total <= room) return folded;
      total -= item.width;
      folded.push(item.id);
    }
  }
  return folded;
}
