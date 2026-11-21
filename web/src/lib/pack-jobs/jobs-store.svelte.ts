import { nonEmptyErrorMessageOr } from '../errors/failure-reason';
import { t } from '../i18n/index.svelte';
import { resourcePush } from '../resource-push/boot';
import { jobsApi, type JobsApi, type JobView } from './jobs-api';
import { isJobId, isLive } from './jobs-format';

export const HISTORY_MAX = 200;
const PAGE = 50;
const LIVE_LIMIT = 200;
const POLL_MS = 10000;
export const TOPIC = 'pack_jobs';

export interface JobsDelta {
  type?: string;
  seq?: number;
  job?: JobView;
  removed?: string[];
}

export interface JobsDeps {
  api: JobsApi;
  subscribe(handler: (frame: JobsDelta) => void): (() => void) | null;
  poll(refresh: () => void): () => void;
  repaint(): void;
}

interface PageGlobals {
  AppEvents?: { subscribe?(handler: (frame: JobsDelta) => void): () => void };
  SessionSidebar?: { repaint?(): void };
}

function pageDeps(): JobsDeps {
  const page = (): PageGlobals => globalThis as PageGlobals;
  return {
    api: jobsApi,
    subscribe: (handler) => page().AppEvents?.subscribe?.((frame) => { if (frame?.type === 'pack_jobs.delta') handler(frame); }) ?? null,
    poll: (refresh) => resourcePush().pushOrPoll(refresh, POLL_MS, [TOPIC]),
    repaint: () => page().SessionSidebar?.repaint?.(),
  };
}

const newest = (a: JobView, b: JobView): number => b.created_at - a.created_at || (a.id < b.id ? 1 : -1);

export class JobsStore {
  rows = $state<Record<string, JobView>>({});
  caller = $state<string | null>(null);
  filter = $state<'live' | 'all'>('live');
  visible = $state(false);
  loading = $state(false);
  error = $state<string | null>(null);
  nextBefore = $state<string | null>(null);
  historyLoaded = $state(false);

  private deps: JobsDeps;
  private lastSeq: number | null = null;
  private flight: Promise<void> | null = null;
  private touched = new Set<string>();
  private moreFlight: Promise<void> | null = null;
  private unsubscribe: (() => void) | null = null;
  private stopPoll: (() => void) | null = null;
  private repaintQueued = false;

  constructor(deps: JobsDeps = pageDeps()) {
    this.deps = deps;
  }

  private scoped(): JobView[] {
    return Object.values(this.rows).filter((j) => this.caller === null || (j.side === 'caller' && j.caller_session === this.caller)).sort(newest);
  }

  get live(): JobView[] {
    return this.scoped().filter(isLive);
  }

  get history(): JobView[] {
    return this.scoped().filter((j) => !isLive(j));
  }

  get shown(): JobView[] {
    return this.filter === 'live' ? this.live : [...this.live, ...this.history];
  }

  get canMore(): boolean {
    return this.visible && this.filter === 'all' && this.historyCount() < HISTORY_MAX && (!this.historyLoaded || this.nextBefore !== null);
  }

  liveFor(callerUuid: string): JobView[] {
    if (!this.unsubscribe || !this.stopPoll) queueMicrotask(() => this.start());
    return Object.values(this.rows).filter((j) => j.side === 'caller' && j.caller_session === callerUuid && isLive(j)).sort(newest);
  }

  start(): void {
    if (!this.unsubscribe) this.unsubscribe = this.deps.subscribe((frame) => this.apply(frame));
    if (this.stopPoll) return;
    this.stopPoll = this.deps.poll(() => void this.resync());
    void this.resync();
  }

  stop(): void {
    this.unsubscribe?.();
    this.stopPoll?.();
    this.unsubscribe = null;
    this.stopPoll = null;
  }

  apply(frame: JobsDelta): void {
    const gap = typeof frame.seq === 'number' && this.lastSeq !== null && frame.seq !== this.lastSeq + 1;
    if (typeof frame.seq === 'number') this.lastSeq = frame.seq;
    for (const id of frame.removed ?? []) {
      delete this.rows[id];
      if (this.flight) this.touched.add(id);
    }
    const job = frame.job;
    if (job && isJobId(job.id)) {
      this.rows[job.id] = job;
      if (this.flight) this.touched.add(job.id);
      this.trim();
    }
    this.repaintSoon();
    if (gap) void this.resync();
  }

  resync(): Promise<void> {
    if (this.flight) return this.flight;
    this.lastSeq = null;
    this.touched = new Set();
    this.loading = true;
    this.flight = (async () => {
      try {
        const page = await this.deps.api.list({ live: true, limit: LIVE_LIMIT });
        const fresh = new Map(page.jobs.filter((j) => isJobId(j.id)).map((j) => [j.id, j] as const));
        for (const [id, job] of fresh) if (!this.touched.has(id)) this.rows[id] = job;
        for (const [id, job] of Object.entries(this.rows)) if (isLive(job) && !fresh.has(id) && !this.touched.has(id)) delete this.rows[id];
        this.error = null;
      } catch (failure) {
        this.error = nonEmptyErrorMessageOr(failure, t('pack.jobs.error.failed'));
      } finally {
        this.loading = false;
        this.flight = null;
        this.touched = new Set();
        this.repaintSoon();
      }
    })();
    return this.flight;
  }

  private historyCount(): number {
    return Object.values(this.rows).filter((j) => !isLive(j)).length;
  }

  private trim(): void {
    const old = Object.values(this.rows).filter((j) => !isLive(j)).sort(newest);
    for (const job of old.slice(HISTORY_MAX)) delete this.rows[job.id];
  }

  loadMore(): Promise<void> {
    if (!this.canMore) return Promise.resolve();
    if (this.moreFlight) return this.moreFlight;
    const asked = this.caller;
    this.moreFlight = (async () => {
      try {
        const page = await this.deps.api.list({ limit: PAGE, before: this.nextBefore, caller: asked });
        if (asked !== this.caller) return;
        for (const job of page.jobs) if (isJobId(job.id) && !this.rows[job.id]) this.rows[job.id] = job;
        this.trim();
        this.nextBefore = this.historyCount() >= HISTORY_MAX ? null : page.next_before;
        this.historyLoaded = true;
        this.error = null;
      } catch (failure) {
        this.error = nonEmptyErrorMessageOr(failure, t('pack.jobs.error.failed'));
      } finally {
        this.moreFlight = null;
        this.repaintSoon();
      }
    })();
    return this.moreFlight;
  }

  setCaller(uuid: string | null): void {
    if (uuid === this.caller) return;
    this.caller = uuid;
    this.nextBefore = null;
    this.historyLoaded = false;
    void this.loadMore();
  }

  setFilter(filter: 'live' | 'all'): void {
    this.filter = filter;
    void this.loadMore();
  }

  setVisible(visible: boolean): void {
    this.visible = visible;
    if (visible) this.start();
    void this.loadMore();
  }

  async stopJob(id: string): Promise<void> {
    await this.deps.api.stop(id);
  }

  private repaintSoon(): void {
    if (this.repaintQueued) return;
    this.repaintQueued = true;
    queueMicrotask(() => {
      this.repaintQueued = false;
      this.deps.repaint();
    });
  }
}

export const jobsStore = new JobsStore();
