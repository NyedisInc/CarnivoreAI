/* the history bar */
import { t } from '../sdk';
import { deleteDraft, fetchDraft, relinkTask, resendRound, saveDraft, sendLiveKept, sendRoundKept } from './board-api';
import type { BoardRevision, BoardSidecar, RoundContext } from './board-model';
import { DraftSync } from './draft-sync';
import { LIVE_ID } from './live-model';
import { carryDraft, roundBody, type Draft } from './tray-model';
import type { Confirm } from './round-confirm';

export type { Confirm };

export class ReviewLoop {
  draft = $state<Draft | null>(null);
  sending = $state(false);
  failed = $state(false);
  busy = $state(false);
  confirm = $state<Confirm | null>(null);
  private sync: DraftSync | null = null;
  private slug: string | null = null;

  constructor(private readonly reload: () => Promise<void>) {}

  async open(slug: string): Promise<void> {
    this.close();
    this.slug = slug;
    this.confirm = null;
    this.failed = false;
    this.sync = new DraftSync(
      { get: () => fetchDraft(slug), put: (body) => saveDraft(slug, body), remove: () => deleteDraft(slug) },
      (d) => (this.draft = d),
    );
    try {
      await this.sync.load();
    } catch {
      this.draft = null;
    }
  }

  close(): void {
    void this.sync?.flush();
    this.sync?.dispose();
    this.sync = null;
    this.slug = null;
    this.draft = null;
  }

  edit(change: (draft: Draft | null) => Draft | null): void {
    this.confirm = null;
    this.failed = false;
    this.sync?.edit(change);
  }

  async remoteChanged(): Promise<void> {
    await this.sync?.remoteChanged().catch(() => undefined);
  }

  clear(): void {
    this.edit(() => null);
  }

  move(from: BoardRevision, to: BoardRevision): void {
    this.edit((d) => (d ? carryDraft(d, from, to, { yes: t('cplug.reviewboard.tray.yes'), no: t('cplug.reviewboard.tray.no') }) : d));
  }

  async send(sidecar: BoardSidecar, context: RoundContext): Promise<void> {
    if (!this.slug || !this.draft || this.sending) return;
    this.sending = true;
    this.failed = false;
    try {
      await this.sync?.flush();
      const title = sidecar.task?.title_at_link ?? sidecar.board.title;
      const item = sidecar.task?.item_id ?? 0;
      const body = roundBody(this.draft, context);
      if (this.draft.revision === LIVE_ID) {
        const sent = await sendLiveKept(this.slug, body, title, item);
        if (sent === 'kept') {
          this.confirm = { title, item, delivered: false, kept: true };
          return;
        }
        this.sync?.sent();
        const state = sent.delivery.state;
        this.confirm = { title, item, delivered: state !== 'undelivered', live: state === 'told' || state === 'posted' ? state : 'undelivered' };
        await this.reload();
        return;
      }
      const out = await sendRoundKept(this.slug, body, title, item);
      if (out === 'kept') {
        this.confirm = { title, item, delivered: false, kept: true };
        return;
      }
      this.sync?.sent();
      this.confirm = { title, item, delivered: out.delivery.state === 'posted', telling: out.tell === 'queued' };
      await this.reload();
    } catch {
      this.failed = true;
    } finally {
      this.sending = false;
    }
  }

  async resend(round: string): Promise<void> {
    if (!this.slug) return;
    this.busy = true;
    try {
      await resendRound(this.slug, round);
      await this.reload();
    } catch {
      this.failed = true;
    } finally {
      this.busy = false;
    }
  }

  async relink(item: number): Promise<void> {
    if (!this.slug) return;
    try {
      await relinkTask(this.slug, item);
      await this.reload();
    } catch {
      this.failed = true;
    }
  }
}
