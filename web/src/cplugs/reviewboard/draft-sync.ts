import { ApiError } from '../sdk';
import type { DraftWire } from './board-model';

export interface DraftApi {
  get(): Promise<DraftWire | null>;
  put(body: DraftWire): Promise<DraftWire>;
  remove(): Promise<void>;
}

export const SAVE_DELAY_MS = 600;

export function staleDraft(error: unknown): DraftWire | null | undefined {
  if (!(error instanceof ApiError) || error.status !== 409) return undefined;
  const payload = error.payload as { detail?: { draft?: DraftWire | null }; draft?: DraftWire | null } | null;
  const holder = payload?.detail && typeof payload.detail === 'object' ? payload.detail : payload;
  return holder && 'draft' in holder ? (holder.draft ?? null) : undefined;
}

export class DraftSync {
  draft: DraftWire | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private saving: Promise<void> | null = null;
  private dirty = false;

  constructor(private readonly api: DraftApi, private readonly onChange: (draft: DraftWire | null) => void, private readonly delay = SAVE_DELAY_MS) {}

  get pending(): boolean {
    return this.dirty;
  }

  private set(draft: DraftWire | null): void {
    this.draft = draft;
    this.onChange(draft);
  }

  async load(): Promise<void> {
    this.set(await this.api.get());
  }

  edit(mutate: (draft: DraftWire | null) => DraftWire | null): void {
    this.set(mutate(this.draft));
    this.dirty = true;
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => void this.flush(), this.delay);
  }

  /* already running */
  async flush(): Promise<void> {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    while (this.saving) await this.saving;
    if (!this.dirty) return;
    this.saving = this.save().finally(() => (this.saving = null));
    await this.saving;
  }

  private async save(): Promise<void> {
    this.dirty = false;
    const sent = this.draft;
    try {
      if (sent === null) await this.api.remove();
      else await this.settle(sent, await this.putOnce(sent));
    } catch {
      this.dirty = true; // could not be reached
    }
  }

  private async putOnce(sent: DraftWire): Promise<DraftWire> {
    try {
      return await this.api.put(sent);
    } catch (error) {
      const current = staleDraft(error);
      if (current === undefined) throw error;
      return this.api.put({ ...sent, rev: current?.rev ?? 0 });
    }
  }

  private settle(sent: DraftWire, saved: DraftWire): void {
    if (this.draft && this.draft.client_round_id === sent.client_round_id) this.set({ ...this.draft, rev: saved.rev });
  }

  async remoteChanged(): Promise<void> {
    if (this.dirty || this.saving) return;
    const server = await this.api.get();
    if (this.dirty || this.saving) return;
    if ((server?.rev ?? 0) !== (this.draft?.rev ?? 0) || (server?.client_round_id ?? null) !== (this.draft?.client_round_id ?? null)) this.set(server);
  }

  sent(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    this.dirty = false;
    this.set(null);
  }

  dispose(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
  }
}
