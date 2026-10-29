/* the home screen */
import type { Layout } from './types';

export const HOME_BOARD_ID = 'home';

export const MAX_BOARDS = 12;

export const MAX_BOARD_NAME = 40;

export const ACTIVE_BOARD_KEY = 'cloudecode.opscenter.home-board.v1';

export const BOARD_PARAM = 'board';

const ID_RE = /^[A-Za-z0-9_-]{1,32}$/;

export interface Board {
  id: string;
  name: string;
  layout: Layout;
}

export interface BoardSummary {
  id: string;
  name: string;
}

export function cleanBoardName(raw: string): string {
  return raw.replace(/\s+/g, ' ').trim().slice(0, MAX_BOARD_NAME);
}

export function parseBoards(value: unknown): Board[] | null {
  if (!Array.isArray(value) || value.length === 0 || value.length > MAX_BOARDS) return null;
  const seen = new Set<string>();
  const out: Board[] = [];
  for (const entry of value) {
    if (!entry || typeof entry !== 'object') return null;
    const { id, name, layout } = entry as Record<string, unknown>;
    if (typeof id !== 'string' || !ID_RE.test(id) || seen.has(id)) return null;
    if (typeof name !== 'string' || name.length === 0 || name.length > MAX_BOARD_NAME) return null;
    if (!layout || typeof layout !== 'object' || Array.isArray(layout)) return null;
    seen.add(id);
    out.push({ id, name, layout: layout as Layout });
  }
  return out;
}

export function pickActiveBoard(boards: readonly { id: string }[], wanted: string | null): string {
  if (wanted && boards.some((board) => board.id === wanted)) return wanted;
  if (boards.some((board) => board.id === HOME_BOARD_ID)) return HOME_BOARD_ID;
  return boards[0]?.id ?? HOME_BOARD_ID;
}

export function readActiveBoard(): string | null {
  try {
    return localStorage.getItem(ACTIVE_BOARD_KEY);
  } catch {
    return null;
  }
}

export function writeActiveBoard(id: string): void {
  try {
    localStorage.setItem(ACTIVE_BOARD_KEY, id);
  } catch {
  }
}

export function mergeBoards(ours: readonly Board[], theirs: readonly Board[], active: string): Board[] {
  const out = theirs.map((board) => (board.id === active ? (ours.find((mine) => mine.id === active) ?? board) : board));
  for (const mine of ours) {
    if (out.length >= MAX_BOARDS) break;
    if (!out.some((board) => board.id === mine.id)) out.push(mine);
  }
  return out;
}
