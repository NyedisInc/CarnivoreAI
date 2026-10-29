
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

export interface NoteState {
  name: string;
  load: LoadState;
  save: SaveState;
  body: string;
  revision: number;
  updatedAt: string | null;
  dirty: boolean;
  conflict: Conflict | null;
}

const live = new Set<NoteStore>();

let listening = false;

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

function listen(): void {
  if (listening) return;
  listening = true;
  subscribe(NOTE_CHANGED_FRAME, (frame) => {
    for (const store of live) store.fold(frame as unknown as Record<string, unknown>);
  });
}

const unsaved = new Map<string, { body: string; revision: number }>();

export function clearUnsaved(): void {
  unsaved.clear();
}

function emptyState(): NoteState {
  return { name: '', load: 'no-session', save: 'idle', body: '', revision: 0, updatedAt: null, dirty: false, conflict: null };
}

export class NoteStore {
  readonly note: NoteState = $state(emptyState());

  private timer: ReturnType<typeof setTimeout> | undefined;

  private inflight: { name: string; pending: Promise<void> } | null = null;

  private cancelTimer(): void {
    if (this.timer !== undefined) clearTimeout(this.timer);
    this.timer = undefined;
  }

  private adopt(payload: NotePayload): void {
    this.note.body = typeof payload.body === 'string' ? payload.body : '';
    this.note.revision = typeof payload.revision === 'number' ? payload.revision : 0;
    this.note.updatedAt = payload.updated_at ?? null;
    this.note.dirty = false;
    this.note.conflict = null;
  }

  async open(name: string): Promise<void> {
    const wanted = (name ?? '').trim();
    if (wanted === this.note.name && (this.note.load === 'loaded' || this.note.load === 'loading')) return;

    if (this.note.dirty && this.note.name) await this.flush();
    this.holdUnsaved();
    this.cancelTimer();
    live.add(this);
    listen();

    Object.assign(this.note, emptyState(), { name: wanted });
    if (!wanted) return;
    this.note.load = 'loading';
    await this.reload(wanted);
  }

  holdUnsaved(): void {
    if (this.note.dirty && this.note.name) unsaved.set(this.note.name, { body: this.note.body, revision: this.note.revision });
  }

  private restoreUnsaved(name: string): void {
    const held = unsaved.get(name);
    if (!held) return;
    unsaved.delete(name);
    const theirs = { revision: this.note.revision, body: this.note.body };
    if (held.body === theirs.body) return;
    this.note.body = held.body;
    this.note.dirty = true;
    if (theirs.revision !== held.revision) {
      this.note.conflict = theirs;
      this.note.save = 'conflict';
      return;
    }
    this.edit(held.body);
  }

  private async reload(name: string): Promise<void> {
    try {
      const body = await authFetch<NotePayload>(`/sessions/${encodeURIComponent(name)}/note`);
      if (this.note.name !== name) return;
      if (this.note.dirty) return;
      this.adopt(body);
      this.note.load = 'loaded';
      this.restoreUnsaved(name);
    } catch (error) {
      if (this.note.name !== name) return;
      this.note.load = error instanceof ApiError && error.status === 404 ? 'no-note-row' : 'failed';
    }
  }

  edit(text: string): void {
    if (this.note.load !== 'loaded') return;
    this.note.body = text;
    this.note.dirty = true;
    if (this.note.conflict) {
      this.cancelTimer();
      return;
    }
    if (this.note.save !== 'saving') this.note.save = 'idle';
    this.cancelTimer();
    this.timer = setTimeout(() => {
      this.timer = undefined;
      void this.save();
    }, AUTOSAVE_MS);
  }

  async save(): Promise<void> {
    this.cancelTimer();
    for (let wait = this.ahead(); wait; wait = this.ahead()) await wait;
    this.cancelTimer();
    const held = this.note;
    if (held.load !== 'loaded' || !held.dirty || !held.name || held.conflict) return;
    await this.send(held.name, held.body, held.revision);
  }

  private ahead(): Promise<void> | null {
    return this.inflight !== null && this.inflight.name === this.note.name ? this.inflight.pending : null;
  }

  private send(name: string, body: string, expected: number): Promise<void> {
    const pending: Promise<void> = this.put(name, body, expected).finally(() => {
      if (this.inflight?.pending === pending) this.inflight = null;
    });
    this.inflight = { name, pending };
    return pending;
  }

  async flush(): Promise<void> {
    await this.save();
  }

  keepTheirs(): void {
    const theirs = this.note.conflict;
    if (!theirs) return;
    this.cancelTimer();
    this.note.body = theirs.body;
    this.note.revision = theirs.revision;
    this.note.dirty = false;
    this.note.conflict = null;
    this.note.save = 'saved';
  }

  async keepMine(): Promise<void> {
    for (let wait = this.ahead(); wait; wait = this.ahead()) await wait;
    const theirs = this.note.conflict;
    if (!theirs || !this.note.name) return;
    await this.send(this.note.name, this.note.body, theirs.revision);
  }

  private async put(name: string, body: string, expected: number): Promise<void> {
    this.note.save = 'saving';
    try {
      const answer = await authFetch<NotePayload>(
        `/sessions/${encodeURIComponent(name)}/note`,
        { method: 'PUT', body: JSON.stringify({ body, expected_revision: expected }) },
      );
      if (this.note.name !== name) return;
      this.note.revision = typeof answer.revision === 'number' ? answer.revision : this.note.revision;
      this.note.updatedAt = answer.updated_at ?? this.note.updatedAt;
      this.note.conflict = null;
      if (this.note.body === body) {
        this.note.dirty = false;
        this.note.save = 'saved';
      } else {
        this.note.save = 'idle';
        this.edit(this.note.body);
      }
    } catch (error) {
      if (this.note.name !== name) return;
      if (!(error instanceof ApiError)) {
        this.note.save = 'failed';
        return;
      }
      if (error.status === 409) {
        const theirs = refusalPayload(error);
        this.note.conflict = theirs ? { revision: theirs.revision ?? 0, body: theirs.body ?? '' } : null;
        this.note.save = 'conflict';
        return;
      }
      this.note.save = error.status === 413 ? 'too_large' : 'failed';
    }
  }

  fold(frame: Record<string, unknown>): void {
    if (frame['tmux_session'] !== this.note.name || !this.note.name) return;
    const revision = frame['revision'];
    if (typeof revision !== 'number' || revision <= this.note.revision) return;
    if (this.note.dirty) return;
    void this.reload(this.note.name);
  }

  dispose(): void {
    this.cancelTimer();
    live.delete(this);
  }

  reset(): void {
    this.cancelTimer();
    this.inflight = null;
    Object.assign(this.note, emptyState());
  }
}
