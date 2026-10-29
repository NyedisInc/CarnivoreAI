
export type RunStatus = 'claimed' | 'running' | 'waiting_on_you' | 'succeeded' | 'failed' | 'skipped' | 'cancelled';

export interface RunUsage {
  input: number;
  output: number;
  cache: number;
  total: number;
}

export interface RunDelivered {
  channel: 'alert';
  kind: 'report' | 'failed';
  alert_key: string;
  at: number;
  state?: 'active' | 'dismissed' | 'resolved' | 'snoozed' | 'gone';
  state_at?: number | null;
}

export interface RunAttachment {
  name: string;
  bytes: number;
  mime: string;
}

export interface RunRow {
  run_id: string;
  automation_id: string;
  number: number;
  trigger: string;
  attempt?: number | null;
  slot_at: number | null;
  status: string;
  reason: string | null;
  skip_count: number | null;
  first_slot_at?: number | null;
  last_slot_at?: number | null;
  started_at: number | null;
  ended_at: number | null;
  created_at?: number | null;
  cost_usd: number | null;
  error: string | null;
  has_report: boolean;
  report_bytes: number | null;
  host: string | null;
  output_empty: boolean | null;
  usage: RunUsage | null;
  delivered: RunDelivered | null;
  attachments: RunAttachment[] | null;
  title?: string | null;
  summary?: string | null;
  notes?: { by?: { kind?: string; name?: string } | null; [field: string]: unknown } | null;
  sessions?: unknown[] | null;
}

export interface RecentRun {
  run_id: string;
  number: number;
  status: string;
  reason: string | null;
  trigger: string;
  attempt: number | null;
  slot_at: number | null;
  started_at: number | null;
  ended_at: number | null;
  skip_count: number | null;
  report_bytes: number | null;
  output_empty: boolean | null;
}

export interface FilesUnder {
  session_uuid: string | null;
  project_id: number | null;
}

export interface ListSignals {
  recent: RecentRun[];
  median_took_s: number | null;
  newest_output_empty: boolean;
  run_count: number;
  newest_number: number | null;
  spends: boolean;
  files_under: FilesUnder;
}

export interface FeedRun extends RunRow {
  automation_name: string;
  report?: unknown;
  report_omitted?: boolean;
}

export type CounterId =
  | 'succeeded_24h'
  | 'failed_24h'
  | 'succeeded_7d'
  | 'failed_7d'
  | 'skipped_7d'
  | 'produced_nothing_7d'
  | 'running'
  | 'waiting_on_you';

export interface RunCounts {
  now: number;
  counters: Record<CounterId, { count: number; automation_ids: string[] }>;
  hosts: string[];
  has_unrecorded_host: boolean;
  next_change_at: number | null;
}

export interface RunReadPrefs {
  automation_runs_seen_at?: string;
  automation_runs_read?: string[];
}

export type ReportSlot =
  | { state: 'pending' }
  | { state: 'unreadable'; reason: 'read_failed' | 'pruned'; message?: string }
  | { state: 'ready'; report: unknown };

export type ReportLookup = (runId: string) => ReportSlot;
