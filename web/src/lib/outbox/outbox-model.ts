
export type OutboxKind = 'reply' | 'answer' | 'round' | 'add';

export type OutboxState = 'pending' | 'sending' | 'failed';

export interface OutboxRequest {
  method: 'POST';
  path: string;
  body: Record<string, unknown>;
}

export interface OutboxLabel {
  text: string;
  where: string;
  list: string | null;
  item: number | null;
  slug?: string;
}

/* the server did not answer */
export interface OutboxError {
  status: number | null;
  code: string | null;
  message: string;
}

export interface OutboxLease {
  tab: string;
  until: number;
}

export interface OutboxEntry {
  id: string;
  kind: OutboxKind;
  request: OutboxRequest;
  ageField: 'retry_age_s' | null;
  after: { path: string; body: Record<string, unknown> } | null;
  label: OutboxLabel;
  created_at: number;
  attempts: number;
  next_at: number;
  state: OutboxState;
  error: OutboxError | null;
  lease: OutboxLease | null;
}

export type NewOutboxEntry = Omit<OutboxEntry, 'created_at' | 'attempts' | 'next_at' | 'state' | 'error' | 'lease'>;

export type OutboxResult =
  | { ok: true; answer: unknown }
  | { ok: false; kept: true; error: OutboxError }
  | { ok: false; kept: false; error: OutboxError; cause: unknown };

export const WAIT_FOR_TRIGGER = Number.MAX_SAFE_INTEGER;

export const MAX_RETRY_AGE_S = 604800;

export function retryAge(entry: Pick<OutboxEntry, 'created_at'>, nowMs: number): number {
  return Math.min(MAX_RETRY_AGE_S, Math.max(0, Math.round((nowMs - entry.created_at) / 1000)));
}

export function isEntry(value: unknown): value is OutboxEntry {
  const v = value as Partial<OutboxEntry> | null;
  return !!v && typeof v === 'object' && typeof v.id === 'string' && typeof v.kind === 'string'
    && !!v.request && typeof v.request.path === 'string' && typeof v.request.body === 'object'
    && !!v.label && typeof v.label.text === 'string' && typeof v.created_at === 'number';
}
