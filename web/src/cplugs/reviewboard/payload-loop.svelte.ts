import { newClientId } from '../sdk';
import { savePayloadDraft, sendRoundKept } from './board-api';
import type { BoardRevision, BoardSidecar, RoundContext } from './board-model';
import { fitsLayer, type BoardLayer } from './layer-payload';
import { draftOf, samePayload, savesOf, stepSave, type Payload } from './payload-model';
import type { Confirm } from './round-confirm';

export const AUTOSAVE_MS = 1500;
export const ECHO_MS = 600;
const MAX_REASON = 120;

export type DraftState = 'idle' | 'pending' | 'saving' | 'saved' | 'failed';

export class PayloadLoop {
  payload = $state<Payload | null>(null);
  viewing = $state<number | null>(null);
  note = $state('');
  sending = $state(false);
  failed = $state(false);
  confirm = $state<Confirm | null>(null);
  draftState = $state<DraftState>('idle');
  draftError = $state('');
  draftRefused = $state(false);
  private slug: string | null = null;
  private revision: string | null = null;
  private key = '';
  private roundId: string | null = null;
  private working: Payload | null = null;
  private persisted: Payload | null = null;
  private armed = false;
  private layer: BoardLayer | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private flight = false;
  private again = false;
  private quietUntil = 0;
  private dirty = false;

  constructor(
    private readonly reload: () => Promise<void>,
    private readonly onload: (payload: Payload, save: number | null) => void,
    private readonly now: () => number = () => Date.now(),
  ) {}

  attach(slug: string, revision: string): void {
    const key = `${slug}|${revision}`;
    if (key === this.key) return;
    void this.flush();
    this.key = key;
    this.slug = slug;
    this.revision = revision;
    this.payload = null;
    this.working = null;
    this.persisted = null;
    this.viewing = null;
    this.note = '';
    this.failed = false;
    this.confirm = null;
    this.roundId = null;
    this.armed = false;
    this.quietUntil = 0;
    this.dirty = false;
    this.draftState = 'idle';
    this.draftError = '';
    this.draftRefused = false;
  }

  private handOver(payload: Payload, save: number | null): void {
    this.quietUntil = this.now() + ECHO_MS;
    this.onload(payload, save);
  }

  received(payload: Payload): void {
    if (!this.armed) return;
    if (this.now() < this.quietUntil) return;
    if (this.layer && !fitsLayer(this.layer, payload)) return this.rejected();
    this.payload = payload;
    this.working = payload;
    this.viewing = null;
    this.confirm = null;
    this.failed = false;
    this.roundId = null;
    this.draftRefused = false;
    this.dirty = true;
    if (samePayload(payload, this.persisted)) {
      this.dirty = false;
      this.clearTimer();
      if (!this.flight) this.draftState = 'saved';
      return;
    }
    this.draftState = 'pending';
    this.clearTimer();
    this.timer = setTimeout(() => void this.writeDraft(), AUTOSAVE_MS);
  }

  rejected(): void {
    this.draftRefused = true;
    this.draftState = 'failed';
  }

  pageReady(revision: BoardRevision): void {
    this.armed = true;
    this.layer = revision.layer ?? null;
    if (this.payload === null) {
      const saves = savesOf(revision);
      const newest = saves.at(-1) ?? null;
      const stored = draftOf(revision);
      if (stored && (!newest || stored.at >= newest.at)) {
        this.payload = this.working = this.persisted = stored.payload;
        this.viewing = newest && samePayload(stored.payload, newest.payload) ? newest.n : null;
        this.draftState = 'saved';
      } else if (newest) {
        this.payload = this.working = newest.payload;
        this.viewing = newest.n;
      }
    }
    if (this.payload) this.handOver(this.payload, this.viewing);
  }

  step(revision: BoardRevision, delta: number): void {
    const saves = savesOf(revision);
    const next = stepSave(saves, this.viewing, delta);
    const chosen = next === null ? null : (saves.find((s) => s.n === next) ?? null);
    const shown = chosen ? chosen.payload : delta > 0 && this.viewing !== null ? this.working : null;
    if (!shown) return;
    this.viewing = chosen ? chosen.n : null;
    this.payload = shown;
    this.roundId = null;
    this.handOver(shown, this.viewing);
  }

  setNote(text: string): void {
    this.note = text;
    this.roundId = null;
  }

  private clearTimer(): void {
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
  }

  flush(): Promise<void> {
    return this.writeDraft(true);
  }

  saveNow(): Promise<void> {
    return this.writeDraft(false);
  }

  private async writeDraft(keepalive = false): Promise<void> {
    this.clearTimer();
    const { slug, revision, key } = this;
    const body = this.working;
    if (!slug || !revision || !body || !this.dirty) return;
    if (this.flight) {
      this.again = true;
      return;
    }
    if (samePayload(body, this.persisted)) {
      if (this.draftState === 'pending') this.draftState = 'saved';
      return;
    }
    this.flight = true;
    this.draftState = 'saving';
    let ok = false;
    try {
      await savePayloadDraft(slug, { revision, payload: body }, keepalive);
      ok = true;
    } catch (error) {
      if (key === this.key) {
        this.draftState = 'failed';
        this.draftError = error instanceof Error ? error.message.slice(0, MAX_REASON) : '';
      }
    } finally {
      this.flight = false;
    }
    if (key === this.key && ok) {
      this.persisted = body;
      if (this.working === body) this.dirty = false;
      this.draftError = '';
      this.draftRefused = false;
      this.draftState = this.timer !== null ? 'pending' : 'saved';
    }
    if (this.again) {
      this.again = false;
      await this.writeDraft(keepalive);
    }
  }

  async send(sidecar: BoardSidecar, revision: string, context: RoundContext): Promise<void> {
    if (!this.slug || !this.payload || this.sending) return;
    this.sending = true;
    this.failed = false;
    try {
      this.roundId ??= newClientId();
      const title = sidecar.task?.title_at_link ?? sidecar.board.title;
      const item = sidecar.task?.item_id ?? 0;
      const out = await sendRoundKept(this.slug, {
        client_round_id: this.roundId, revision, answers: [], anchor_notes: [], note: this.note.trim(), context, payload: this.payload,
      }, title, item);
      if (out === 'kept') {
        this.confirm = { title, item, delivered: false, kept: true };
        return;
      }
      this.viewing = out.round.save ?? this.viewing;
      this.confirm = { title, item, delivered: out.delivery.state === 'posted', telling: out.tell === 'queued' };
      this.note = '';
      this.roundId = null;
      await this.reload();
    } catch {
      this.failed = true;
    } finally {
      this.sending = false;
    }
  }
}
