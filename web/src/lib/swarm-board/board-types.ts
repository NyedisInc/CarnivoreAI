
export const COLUMNS = ['todo', 'in_progress', 'review', 'done'] as const;
export type CardColumn = (typeof COLUMNS)[number];

export interface CardHolder {
  agent_id: number;
  name: string | null;
  since: number | null;
  started_at: number | null;
  beat_at: number | null;
}

export interface CardView {
  id: number;
  list_key: string;
  project_id: number | null;
  title: string;
  text: string;
  column: CardColumn;
  state: string;
  position: number;
  queue_index: number | null;
  group_id: number | null;
  holder: CardHolder | null;
  legacy_claim: string | null;
  last_holder: number | null;
  dealt_to: number | null;
  parent: number | null;
  lane_role: string | null;
  children: { total: number; done: number; in_review: number };
  origin: { kind: string; ref: string };
  paused: { mode: string; by: number | null; at: number | null } | null;
  mark: { name: string; at: number | null } | null;
  accepted_at: number | null;
  report_id: number | null;
  pin: { agent_id: number | null; place: boolean };
  progress: number | null;
  result: string;
  handoff: string;
  how_to_validate: string;
  validate_link: string;
  proof: string | null;
  validation: Record<string, unknown> | null;
  phone_sent_at: number | null;
  summary: string;
  queued: boolean;
  archived_at: number | null;
  auto_promote: boolean;
  owner_note: string;
  revision: number;
  created_at: number;
  updated_at: number;
}

export type CardCounts = Record<CardColumn, number>;

export interface CardLane {
  project_id: number | null;
  list_key: string;
  name: string;
  rules: Record<string, unknown>;
  counts: CardCounts;
  columns: Record<CardColumn, CardView[]>;
}

export interface CardBoard {
  scope: string;
  filter: 'all' | 'mine';
  lanes: CardLane[];
  win: { through_review_today: number; in_review: number; since: number };
  capacity: Record<string, unknown> | null;
}

export type BoardScope = { kind: 'sysop' } | { kind: 'company'; id: number } | { kind: 'project'; id: number };

export type ArchivedChoice = 'hide' | 'only';

export interface BoardQuery {
  scope: BoardScope;
  filter: 'all' | 'mine';
  archived?: ArchivedChoice;
}

export function scopeParam(scope: BoardScope): string {
  return scope.kind === 'sysop' ? 'sysop' : `${scope.kind}:${scope.id}`;
}
