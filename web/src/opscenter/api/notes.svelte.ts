
import { ApiError, authFetch } from './auth.svelte';
import { subscribe } from './events.svelte';

export const AUTOSAVE_MS = 1500;

export const NOTE_CHANGED_FRAME = 'session.note.changed';

export type SaveState = 'idle' | 'saving' | 'saved' | 'conflict' | 'failed' | 'too_large';

export type LoadState = 'no-session' | 'loading' | 'loaded' | 'failed' | 'no-note-row';

export interface Conflict {
  revision: number;
  body: string;
}

interface NotePayload {
  status?: string;
  revision?: number;
  body?: string;
  updated_at?: string | null;
  detail?: string | null;
}

export const note = $state<{
  name: string;
  load: LoadState;
  save: SaveState;
  body: string;
  revision: number;
  updatedAt: string | null;
  dirty: boolean;
  conflict: Conflict | null;
}>({
  name: '',
  load: 'no-session',
  save: 'idle',
  body: '',
  revision: 0,
  updatedAt: null,
  dirty: false,
  conflict: null,
});

let timer: ReturnType<typeof setTimeout> | undefined;

/* the change frame */
let listening = false;

let inflight: { name: string; pending: Promise<void> } | null = null;

function isNotePayload(value: unknown): value is Required<Pick<NotePayload, 'revision' | 'body'>> {
  if (!value || typeof value !== 'object') return false;
  const held = value as Record<string, unknown>;
  return typeof held['revision'] === 'number' && typeof held['body'] === 'string';
}

function refusalPayload(error: ApiError): NotePayload | null {
  const body = error.payload;
  if (isNotePayload(body)) return body as NotePayload;
  if (body && typeof body === 'object') {
    const inner = (body as Record<string, unknown>)['detail'];
    if (isNotePayload(inner)) return inner as NotePayload;
  }
  return null;
}

function cancelTimer(): void {
  if (timer !== undefined) clearTimeout(timer);
  timer = undefined;
}

function adopt(payload: NotePayload): void {
  note.body = typeof payload.body === 'string' ? payload.body : '';
  note.revision = typeof payload.revision === 'number' ? payload.revision : 0;
  note.updatedAt = payload.updated_at ?? null;
  note.dirty = false;
  note.conflict = null;
}

export async function open(name: string): Promise<void> {
  const wanted = (name ?? '').trim();
  if (wanted === note.name && (note.load === 'loaded' || note.load === 'loading')) return;

  if (note.dirty && note.name) await flush();
  cancelTimer();
  listen();

  note.name = wanted;
  note.body = '';
  note.revision = 0;
  note.updatedAt = null;
  note.dirty = false;
  note.conflict = null;
  note.save = 'idle';

  if (!wanted) {
    note.load = 'no-session';
    return;
  }
  note.load = 'loading';
  await reload(wanted);
}

async function reload(name: string): Promise<void> {
  try {
    const body = await authFetch<NotePayload>(`/sessions/${encodeURIComponent(name)}/note`);
    if (note.name !== name) return;
    if (note.dirty) return;
    adopt(body);
    note.load = 'loaded';
  } catch (error) {
    if (note.name !== name) return;
    note.load = error instanceof ApiError && error.status === 404 ? 'no-note-row' : 'failed';
  }
}

export function edit(text: string): void {
  if (note.load !== 'loaded') return;
  note.body = text;
  note.dirty = true;
  if (note.conflict) {
    cancelTimer();
    return;
  }
  if (note.save !== 'saving') note.save = 'idle';
  cancelTimer();
  timer = setTimeout(() => {
    timer = undefined;
    void save();
  }, AUTOSAVE_MS);
}

export async function save(): Promise<void> {
  cancelTimer();
  for (let wait = ahead(); wait; wait = ahead()) await wait;
  cancelTimer();
  if (note.load !== 'loaded' || !note.dirty || !note.name || note.conflict) return;
  await send(note.name, note.body, note.revision);
}

function ahead(): Promise<void> | null {
  return inflight !== null && inflight.name === note.name ? inflight.pending : null;
}

function send(name: string, body: string, expected: number): Promise<void> {
  const pending: Promise<void> = put(name, body, expected).finally(() => {
    if (inflight?.pending === pending) inflight = null;
  });
  inflight = { name, pending };
  return pending;
}

export async function flush(): Promise<void> {
  await save();
}

export function keepTheirs(): void {
  const theirs = note.conflict;
  if (!theirs) return;
  cancelTimer();
  note.body = theirs.body;
  note.revision = theirs.revision;
  note.dirty = false;
  note.conflict = null;
  note.save = 'saved';
}

export async function keepMine(): Promise<void> {
  for (let wait = ahead(); wait; wait = ahead()) await wait;
  const theirs = note.conflict;
  if (!theirs || !note.name) return;
  await send(note.name, note.body, theirs.revision);
}

async function put(name: string, body: string, expected: number): Promise<void> {
  note.save = 'saving';
  try {
    const answer = await authFetch<NotePayload>(
      `/sessions/${encodeURIComponent(name)}/note`,
      { method: 'PUT', body: JSON.stringify({ body, expected_revision: expected }) },
    );
    if (note.name !== name) return;
    note.revision = typeof answer.revision === 'number' ? answer.revision : note.revision;
    note.updatedAt = answer.updated_at ?? note.updatedAt;
    note.conflict = null;
    if (note.body === body) {
      note.dirty = false;
      note.save = 'saved';
    } else {
      note.save = 'idle';
      edit(note.body);
    }
  } catch (error) {
    if (note.name !== name) return;
    if (!(error instanceof ApiError)) {
      note.save = 'failed';
      return;
    }
    if (error.status === 409) {
      const theirs = refusalPayload(error);
      note.conflict = theirs
        ? { revision: theirs.revision ?? 0, body: theirs.body ?? '' }
        : null;
      note.save = 'conflict';
      return;
    }
    note.save = error.status === 413 ? 'too_large' : 'failed';
  }
}

function listen(): void {
  if (listening) return;
  listening = true;
  subscribe(NOTE_CHANGED_FRAME, (frame) => {
    const held = frame as unknown as Record<string, unknown>;
    if (held['tmux_session'] !== note.name || !note.name) return;
    const revision = held['revision'];
    if (typeof revision !== 'number' || revision <= note.revision) return;
    if (note.dirty) return;
    void reload(note.name);
  });
}

export function reset(): void {
  cancelTimer();
  inflight = null;
  note.name = '';
  note.load = 'no-session';
  note.save = 'idle';
  note.body = '';
  note.revision = 0;
  note.updatedAt = null;
  note.dirty = false;
  note.conflict = null;
}
