
export interface Split {
  conversation: string | null;
  message_uuid: string | null;
  line: number | null;
  at: string | null;
}

export interface Began {
  kind: string;
  from_conversation: string | null;
  basis: string | null;
  at: string | null;
  split: Split | null;
}

export interface ActivityRun {
  state: 'busy' | 'idle';
  start: string;
  end: string;
  busy_seconds: number;
}

export interface Bar {
  conversation_id: string;
  current: boolean;
  level: string | null;
  began: Began | null;
  started_at: string | null;
  ended_at: string | null;
  activity?: ActivityRun[] | null;
  busy_seconds?: number | null;
}

export type MarkKind = 'compact' | 'bookmark' | 'restart' | 'restore';

export interface Mark {
  id: string;
  kind: MarkKind;
  conversation_id: string;
  at: string | null;
  entry_uuid: string | null;
  label: string;
  snippet: string;
  can_peek: boolean;
  trigger: string | null;
  pre_tokens: number | null;
  bookmark_id: number | null;
  created_by: string | null;
  point_id: string | null;
  reason: string | null;
  pinned: boolean | null;
  failsafe: boolean | null;
  turns: number | null;
}

export interface Gap {
  id: string;
  conversation_id: string;
  start: string;
  end: string | null;
  open: boolean;
}

export interface Attention {
  kind: string;
  start: string;
  end: string | null;
}

export interface SessionTimeline {
  session_uuid: string;
  session_row_id: number;
  family: string;
  current_conversation: string | null;
  now: string;
  bars: Bar[];
  marks: Mark[];
  gaps: Gap[];
  attention?: Attention[];
}

export type FilterKey = 'bookmarks' | 'compacts' | 'restarts' | 'sleeps' | 'restores';

export type Filters = Record<FilterKey, boolean>;
