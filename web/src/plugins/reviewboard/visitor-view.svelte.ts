import { untrack } from 'svelte';
import { registerVisitorRevisionOpener, visitorRevisionSources, type VisitorAnswerBody, type VisitorRevision, type VisitorRevisionAnswers, type VisitorRevisionFollow } from './board-visitor-revisions.svelte';
import type { BoardRevision } from './board-model';
import { visitorsOf } from './visitor-lines';

export interface VisitorFrame {
  load(payload: Record<string, unknown>, save: number | null): void;
  readOnly(readonly: boolean): void;
}

interface Selected { revision: string; number: number }

interface ReadBody { revision: string; number: number; updated_at: number; print: string | undefined; body: VisitorAnswerBody }

export class VisitorView {
  readFailed = $state(false);
  private slug = $state<string | null>(null);
  private follows = $state.raw<VisitorRevisionFollow[]>([]);
  private selected = $state.raw<Selected | null>(null);
  private read = $state.raw<ReadBody | null>(null);
  private frameHolds = false;

  constructor() {
    $effect(() => {
      const slug = this.slug;
      const sources = visitorRevisionSources();
      const follows = untrack(() => (slug ? sources.map((source) => source.follow(slug)) : []));
      this.follows = follows;
      return () => { for (const follow of follows) follow.stop(); };
    });
    $effect(() => {
      const row = this.shownRow;
      if (!row) return;
      const { revision, number, updated_at, print } = row;
      const have = untrack(() => this.read);
      if (have && have.revision === revision && have.number === number && have.updated_at === updated_at && have.print === print) return;
      const found = untrack(() => this.follows.find((follow) => follow.rows().some((one) => one.number === number && one.revision === revision)));
      if (!found) return;
      let current = true;
      found.answers(revision, number).then((body) => {
        if (!current) return;
        if (body) this.read = { revision, number, updated_at, print, body };
        this.readFailed = false;
      }, () => {
        if (current) this.readFailed = true;
      });
      return () => { current = false; };
    });
  }

  get number(): number | null {
    return this.selected?.number ?? null;
  }

  get rows(): VisitorRevision[] {
    return this.follows.flatMap((follow) => follow.rows());
  }

  private get shownRow(): VisitorRevision | null {
    const pick = this.selected;
    return pick ? (this.of(pick.revision).find((row) => row.number === pick.number) ?? null) : null;
  }

  get shown(): VisitorRevisionAnswers | null {
    const row = this.shownRow;
    const read = this.read;
    return row && read && read.revision === row.revision && read.number === row.number ? { ...row, body: read.body } : null;
  }

  follow(slug: string | null): void {
    this.slug = slug;
  }

  stop(): void {
    this.slug = null;
    this.selected = null;
  }

  select(revision: string | null, number: number | null): void {
    this.selected = revision !== null && number !== null ? { revision, number } : null;
    this.readFailed = false;
  }

  of(revision: string | undefined): VisitorRevision[] {
    return revision ? visitorsOf(this.rows, revision) : [];
  }

  bindFrame(page: () => BoardRevision | null, frame: () => VisitorFrame | null, ownerPage: (revision: BoardRevision) => void): void {
    $effect(() => {
      const on = page();
      const target = frame();
      const payload = this.shown?.body.payload;
      if (!on || !target) return;
      untrack(() => {
        if (payload) this.loadInto(target, payload);
        else if (this.frameHolds) {
          target.readOnly(false);
          ownerPage(on);
          this.frameHolds = false;
        }
      });
    });
  }

  frameReady(frame: VisitorFrame | null): boolean {
    const payload = this.shown?.body.payload;
    if (!payload || !frame) return false;
    this.loadInto(frame, payload);
    return true;
  }

  private loadInto(frame: VisitorFrame, payload: Record<string, unknown>): void {
    frame.readOnly(true);
    frame.load(payload, null);
    this.frameHolds = true;
  }

  claimOpener(open: (slug: string, revision: string, number: number) => void): () => void {
    return registerVisitorRevisionOpener(open);
  }
}
