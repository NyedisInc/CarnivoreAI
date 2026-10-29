import type { BoardLayer } from './layer-payload';

export const DRAFTS_TOPIC = 'cplug.reviewboard.drafts';
export const BOARDS_TOPIC = 'cplug.reviewboard.boards';
export const BASE = '/cplugs/reviewboard';
export const COLLAPSE_AFTER = 20;
export const MAIN_VIEW = 'main';

export interface BoardView { id: string; label: string; file: string }
export interface BoardOption { id: string; label: string }
export interface BoardPrompt { id: string; kind: 'choice' | 'multi' | 'check' | 'question'; label: string; options?: BoardOption[] | null; anchor?: string | null }
export interface BoardAnchor { id: string; label: string }
export interface BoardSave { n: number; at: string; payload: Record<string, unknown>; note?: string | null }
export interface PayloadDraft { at: string; payload: Record<string, unknown> }
export interface PayloadDiff { previous?: string | null; added: string[]; removed: string[]; changed: string[]; more: number }
export interface BoardRevision {
  id: string;
  n: number;
  created_at: string;
  summary: string;
  answers_round: string | null;
  viewport: number;
  views: BoardView[];
  prompts: BoardPrompt[];
  anchors: BoardAnchor[];
  payload_mode?: boolean | null;
  saves?: BoardSave[] | null;
  draft?: PayloadDraft | null;
  layer?: BoardLayer | null;
  max_width?: number | null;
  milestone?: string | null;
  inline_picks?: boolean | null;
  stamp?: string;
}
export interface AnswerRow { prompt: string; options?: string[] | null; checked?: boolean | null; text?: string | null; note: string }
export interface AnchorNoteRow { anchor: string; text: string }
export interface RoundContext { theme?: string | null; width?: number | null; fit?: FitMode | null; view?: string | null }
export interface RoundDelivery { state: 'pending' | 'posted' | 'undelivered'; item_id?: number | null; message_id?: number | null; reason?: string | null }
export interface BoardRound {
  id: string;
  n: number;
  revision: string;
  client_round_id: string;
  sent_at: string;
  context: RoundContext;
  answers: AnswerRow[];
  anchor_notes: AnchorNoteRow[];
  note: string;
  unanswered: string[];
  payload?: Record<string, unknown> | null;
  save?: number | null;
  diff?: PayloadDiff | null;
  delivery: RoundDelivery;
}
export interface LiveDraft {
  seq: number;
  updated_at: string;
  summary: string;
  viewport: number;
  views: BoardView[];
  prompts: BoardPrompt[];
  anchors: BoardAnchor[];
  max_width?: number | null;
  inline_picks?: boolean | null;
}
export interface LiveSendRow { n: number; at: string; seq: number; note: string; delivery: { state: 'pending' | 'told' | 'posted' | 'undelivered'; via?: string | null; reason?: string | null } }
export interface LiveSlot { started_at: string; by: { actor: string; session?: string | null }; draft: LiveDraft; sends: LiveSendRow[]; sends_total: number }
export interface BoardSidecar {
  board: { slug: string; title: string; kind: string };
  live?: LiveSlot | null;
  task: { item_id: number; computer: string; list?: string | null; title_at_link?: string | null } | null;
  revisions: BoardRevision[];
  rounds: BoardRound[];
  ext?: Record<string, unknown>;
}
export function isScratch(sidecar: BoardSidecar | null): boolean {
  return !!sidecar?.ext && Object.prototype.hasOwnProperty.call(sidecar.ext, 'scratch');
}
export interface BoardAnswer { slug: string; status: string; state: string; etag: string; sidecar: BoardSidecar | null }
export interface BoardListRow {
  slug: string; status: string; title: string | null; revisions: number; rounds: number; state: string | null; last_activity: string | null;
  project?: string | null;
  task?: { item_id: number; computer: string; github_issue?: number | null } | null;
  closed_at?: string | null;
  task_title?: string | null;
}
export interface BoardList { boards: BoardListRow[] }
export interface TicketAnswer { url: string; expires_in: number; view: string }

export interface HistoryItem { kind: 'revision' | 'round'; id: string; revision: string; at: string; n: number; undelivered: boolean; milestone?: string | null }

export function historyItems(sidecar: BoardSidecar): HistoryItem[] {
  const items: HistoryItem[] = [
    ...sidecar.revisions.map((r): HistoryItem => ({ kind: 'revision', id: r.id, revision: r.id, at: r.created_at, n: r.n, undelivered: false, milestone: r.milestone ?? null })),
    ...sidecar.rounds.map((r): HistoryItem => ({ kind: 'round', id: r.id, revision: r.revision, at: r.sent_at, n: r.n, undelivered: r.delivery.state === 'undelivered' })),
  ];
  const rank = (i: HistoryItem): number => (i.kind === 'revision' ? 0 : 1);
  return items.sort((a, b) => (a.at < b.at ? -1 : a.at > b.at ? 1 : rank(a) - rank(b) || a.n - b.n));
}

export interface VisibleHistory { items: HistoryItem[]; folded: { from: number; to: number } | null }

export function visibleHistory(items: readonly HistoryItem[], revisions: number, expanded: boolean): VisibleHistory {
  if (expanded || revisions <= COLLAPSE_AFTER) return { items: [...items], folded: null };
  const hiddenTo = revisions - COLLAPSE_AFTER;
  const number = (id: string): number => (/^r[0-9]+$/.test(id) ? Number(id.slice(1)) : Number.POSITIVE_INFINITY);
  return { items: items.filter((i) => number(i.revision) > hiddenTo), folded: { from: 1, to: hiddenTo } };
}

export function latestRevision(sidecar: BoardSidecar): BoardRevision | null {
  return sidecar.revisions.at(-1) ?? null;
}

export function revisionById(sidecar: BoardSidecar, id: string | null): BoardRevision | null {
  return id === null ? null : (sidecar.revisions.find((r) => r.id === id) ?? null);
}

export function stepRevision(sidecar: BoardSidecar, current: string, delta: number): string {
  const at = sidecar.revisions.findIndex((r) => r.id === current);
  if (at < 0) return current;
  return sidecar.revisions[Math.min(sidecar.revisions.length - 1, Math.max(0, at + delta))]!.id;
}

export type FitMode = 'actual' | 'fit';

export const BOARD_MAX_WIDTH = 760;

export function hasSetWidth(revision: Pick<BoardRevision, 'layer' | 'max_width'> | null): boolean {
  return !!revision && (!!revision.layer || !!revision.max_width);
}

export function widthCap(revision: Pick<BoardRevision, 'layer' | 'max_width'> | null, fullWidth: boolean): number | null {
  if (!revision) return null;
  if (fullWidth) return null;
  if (revision.layer) return BOARD_MAX_WIDTH;
  return revision.max_width || null;
}

/* the page frame */
export function cappedRoom(room: number, cap: number | null): number {
  return cap !== null && room > cap ? cap : room;
}

export function defaultFit(viewport: number, room: number): FitMode {
  return room <= 0 || viewport <= room ? 'actual' : 'fit';
}

export function fitScale(viewport: number, room: number): number {
  return room <= 0 || viewport <= 0 ? 1 : Math.min(1, Math.max(0.1, room / viewport));
}

export function frameWidth(viewport: number, room: number, scale: number): number {
  return scale < 1 ? viewport : Math.max(viewport, room);
}

export function paramsFromSearch(search: string): { board: string | null; rev: string | null } {
  const params = new URLSearchParams(search);
  const board = params.get('board');
  const rev = params.get('rev');
  return { board: board && /^[0-9]{8}-[a-z0-9-]{1,48}$/.test(board) ? board : null, rev: rev && /^r[1-9][0-9]*$/.test(rev) ? rev : null };
}

export interface DraftWire {
  rev: number;
  revision: string;
  answers: AnswerRow[];
  anchor_notes: AnchorNoteRow[];
  note: string;
  client_round_id: string;
}
export interface RoundWire {
  client_round_id: string;
  revision: string;
  answers: AnswerRow[];
  anchor_notes: AnchorNoteRow[];
  note: string;
  context: RoundContext;
  payload?: Record<string, unknown>;
}
export interface PayloadDraftWire { revision: string; payload: Record<string, unknown> }
export interface PayloadDraftAnswer { revision: string; draft: { at: string }; etag: string; changed: boolean }
export interface RoundAnswer { round: BoardRound; etag: string; delivery: RoundDelivery; state: string; duplicate: boolean; tell?: 'queued' | 'nothing' | 'failed' | null }
export interface TaskChoice { id: number; title: string; status: string }

export function closedNewestFirst(rows: readonly BoardListRow[]): BoardListRow[] {
  const at = (row: BoardListRow): number => {
    const ms = row.closed_at ? Date.parse(row.closed_at) : NaN;
    return Number.isNaN(ms) ? -Infinity : ms;
  };
  return [...rows].sort((a, b) => {
    const gap = at(b) - at(a);
    return Number.isNaN(gap) ? 0 : gap;
  });
}
