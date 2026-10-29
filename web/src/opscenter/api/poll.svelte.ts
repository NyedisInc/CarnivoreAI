
import { auth, initAuth, ApiError, authFetch } from './auth.svelte';
import { isDemo } from './demo';
import { t } from '../../lib/i18n/index.svelte';
import { whenListingPushBooted } from '../../lib/listing-push/boot';
import { resourcePush } from '../../lib/resource-push/boot';
import { LIVENESS, type FrameBodies } from '../../lib/resource-push/store';

export type ResourceStatus = 'loading' | 'ok' | 'error' | 'unavailable' | 'signed-out';

export interface Resource<T> {
  readonly status: ResourceStatus;
  readonly data: T | null;
  readonly fetchedAt: number | null;
  readonly error: string | null;
  refresh(explicit?: boolean): Promise<void>;
  push?(value: T): void;
  stop(): void;
}

export interface ResourceOptions<T> {
  intervalMs: number;
  name: string;
  demo?: () => T;
  pushed?: readonly string[];
  topics?: readonly string[];
  body?: { key: string; read: (body: unknown) => T | null; renewMs?: number };
  afterPush?: () => void;
  pollWhile?: () => boolean;
}

interface PushSource {
  isLive(): boolean;
  onChange(fn: (names: string[]) => void): () => void;
}

export function pushedRows<T>(name: string): T[] | null {
  const found = (globalThis as { ListingPush?: { rows?(n: string): T[] | null } }).ListingPush;
  return found && typeof found.rows === 'function' ? found.rows(name) : null;
}

async function provisionalRows<T>(name: string): Promise<T[] | null> {
  const found = (globalThis as { ListingPush?: { provisionalRows?(n: string): Promise<T[] | null> } }).ListingPush;
  return found && typeof found.provisionalRows === 'function' ? found.provisionalRows(name) : null;
}

function hasProvisional(): boolean {
  return typeof (globalThis as { ListingPush?: { provisionalRows?: unknown } }).ListingPush?.provisionalRows === 'function';
}

const routeFlights = new Map<string, Promise<unknown>>();

export async function listingRows<T>(name: string, path: string): Promise<T[]> {
  const pushed = pushedRows<T>(name);
  if (pushed) return pushed;
  if (hasProvisional()) {
    const cached = await provisionalRows<T>(name);
    if (cached) return cached;
    const live = pushedRows<T>(name);
    if (live) return live;
  }
  let flight = routeFlights.get(path) as Promise<T[]> | undefined;
  if (!flight) {
    flight = authFetch<T[]>(path).finally(() => routeFlights.delete(path));
    routeFlights.set(path, flight);
  }
  return structuredClone(await flight);
}

export function pushedMeta(name: string): Record<string, unknown> | null {
  const found = (globalThis as { ListingPush?: { meta?(n: string): Record<string, unknown> | null } }).ListingPush;
  return found && typeof found.meta === 'function' ? found.meta(name) : null;
}

function pushSource(): PushSource | null {
  const found = (globalThis as { ListingPush?: PushSource }).ListingPush;
  return found && typeof found.isLive === 'function' && typeof found.onChange === 'function' ? found : null;
}

const MAX_BACKOFF_MS = 60000;

const registry = new Set<{
    refresh: () => Promise<void>;
    restart: () => void;
    pause: () => void;
    describe: () => { name: string; intervalMs: number; running: boolean };
}>();

export function listPollers(): { name: string; intervalMs: number }[] {
  const out: { name: string; intervalMs: number }[] = [];
  for (const entry of registry) {
    const d = entry.describe();
    if (d.running) out.push({ name: d.name, intervalMs: d.intervalMs });
  }
  return out;
}

export function refreshAll(): void {
  for (const entry of registry) void entry.refresh();
}

export function restartAll(): void {
  initAuth();
  for (const entry of registry) entry.restart();
}

export function pauseAll(): void {
  initAuth();
  for (const entry of registry) entry.pause();
}

export function resource<T>(fetcher: () => Promise<T>, options: ResourceOptions<T>): Resource<T> {
  const held = $state<{
    status: ResourceStatus;
    data: T | null;
    fetchedAt: number | null;
    error: string | null;
  }>({ status: 'loading', data: null, fetchedAt: null, error: null });

  if (isDemo() && options.demo) {
    held.data = options.demo();
    held.status = 'ok';
    held.fetchedAt = Date.now();
    return {
      get status() { return held.status; },
      get data() { return held.data; },
      get fetchedAt() { return held.fetchedAt; },
      get error() { return held.error; },
      async refresh() {  },
      push() {  },
      stop() {  },
    };
  }

  let timer: ReturnType<typeof setTimeout> | undefined;
  let inFlight: Promise<void> | null = null;
  let failures = 0;
  let stopped = false;
  let disposed = false;
  let missed = false;
  let settled = false;
  let lastRead = 0;

  function delay(): number {
    if (failures === 0) return options.intervalMs;
    return Math.min(options.intervalMs * 2 ** failures, MAX_BACKOFF_MS);
  }

  function schedule(): void {
    if (stopped || options.intervalMs <= 0) return;
    if (timer !== undefined) clearTimeout(timer);
    timer = undefined;
    if (options.pushed && failures === 0 && pushSource()?.isLive()) return;
    if (topicsLive()) {
      const renew = options.body?.renewMs;
      if (renew !== undefined) timer = setTimeout(tick, lastRead ? Math.max(lastRead + 2 * renew - Date.now(), 0) : 2 * renew);
      return;
    }
    if (options.pollWhile && failures === 0 && pushSource()?.isLive() && !options.pollWhile()) return;
    timer = setTimeout(tick, delay());
  }

  function topicsLive(): boolean {
    const topics = options.topics;
    if (!topics || topics.length === 0 || failures !== 0) return false;
    const push = resourcePush();
    return topics.every((topic) => push.isLive(topic));
  }

  function signedOut(): boolean {
    return auth.state === 'signed-out';
  }

  let rerun = false;

  function dropRows(): void {
    held.status = 'signed-out';
    held.data = null;
    held.fetchedAt = null;
    held.error = null;
  }

  async function readOnce(): Promise<void> {
    try {
      const value = await fetcher();
      held.data = value;
      held.status = 'ok';
      held.fetchedAt = Date.now();
      lastRead = held.fetchedAt;
      held.error = null;
      failures = 0;
    } catch (error) {
      failures += 1;
      if (error instanceof ApiError && error.status === 401) {
        dropRows();
      } else if (error instanceof ApiError && (error.status === 404 || error.status === 501)) {
        held.status = 'unavailable';
        held.error = error.message;
      } else {
        held.status = 'error';
        held.error = error instanceof Error ? error.message : t('opscenter.value.read_failed');
      }
    }
  }

  async function run(): Promise<void> {
    if (inFlight) {
      rerun = true;
      return inFlight;
    }
    inFlight = (async () => {
      try {
        do {
          rerun = false;
          await readOnce();
        } while (rerun && !disposed);
      } finally {
        inFlight = null;
        settled = true;
      }
    })();
    return inFlight;
  }

  async function tick(): Promise<void> {
    if (stopped) return;
    if (signedOut()) {
      dropRows();
      timer = undefined;
      return;
    }
    if (settled && typeof document !== 'undefined' && document.hidden) {
      missed = true;
      if (options.body?.renewMs === undefined || !topicsLive()) schedule();
      return;
    }
    missed = false;
    await run();
    schedule();
  }

  const onVisible = (): void => {
    if (typeof document === 'undefined' || document.hidden) return;
    if (!missed) return;
    missed = false;
    void tick();
  };
  if (typeof document !== 'undefined') {
    document.addEventListener('visibilitychange', onVisible);
  }

  let offPush: (() => void) | null = null;
  const attachPush = (): void => {
    const source = pushSource();
    if (!source || disposed || offPush) return;
    offPush = source.onChange((names) => {
      if (disposed || signedOut()) return;
      const touched = names.some((n) => n === '$live' || options.pushed!.includes(n));
      if (!touched) return;
      if (source.isLive()) void run().then(() => { if (!stopped) schedule(); });
      else if (!stopped && timer === undefined) schedule();
    });
    if (source.isLive() && settled) void run().then(() => { if (!stopped) schedule(); });
  };
  if (options.pushed) {
    attachPush();
    if (!offPush) whenListingPushBooted(attachPush);
  }

  function applyBody(bodies: FrameBodies | undefined): boolean {
    const spec = options.body;
    if (!spec || !bodies || !(spec.key in bodies) || inFlight) return false;
    if (spec.renewMs !== undefined && Date.now() - lastRead >= spec.renewMs) return false;
    const value = spec.read(bodies[spec.key]);
    if (value === null) return false;
    held.data = value;
    held.status = 'ok';
    held.fetchedAt = Date.now();
    held.error = null;
    failures = 0;
    settled = true;
    return true;
  }

  let offTopics: (() => void) | null = null;
  if (options.topics && options.topics.length) {
    offTopics = resourcePush().onChange((names, bodies) => {
      if (disposed || signedOut()) return;
      const named = names.some((n) => options.topics!.includes(n));
      if (!named && (stopped || !names.includes(LIVENESS))) return;
      if (topicsLive()) {
        if (named && applyBody(bodies)) {
          if (!stopped) schedule();
          if (options.afterPush) options.afterPush();
          return;
        }
        void run().then(() => {
          if (!stopped) schedule();
          if (!disposed && options.afterPush) options.afterPush();
        });
      } else if (timer === undefined) {
        schedule();
      }
    });
  }

  const entry = {
    describe: () => ({ name: options.name, intervalMs: options.intervalMs, running: !stopped && timer !== undefined }),
    async refresh(explicit = false): Promise<void> {
      if (disposed || (stopped && !explicit) || signedOut()) return;
      if (explicit && inFlight) await inFlight;
      if (disposed || signedOut()) return;
      await run();
      if (!stopped && timer === undefined) schedule();
    },
    restart(): void {
      stopped = false;
      failures = 0;
      void tick();
    },
    pause(): void {
      stopped = true;
      if (timer !== undefined) clearTimeout(timer);
      timer = undefined;
      if (signedOut()) dropRows();
    },
  };
  registry.add(entry);

  if (auth.state === 'signed-out') {
    dropRows();
  } else {
    void tick();
  }

  return {
    get status() { return held.status; },
    get data() { return held.data; },
    get fetchedAt() { return held.fetchedAt; },
    get error() { return held.error; },
    refresh: entry.refresh,
    push(value: T): void {
      if (disposed || signedOut()) return;
      held.data = value;
      held.status = 'ok';
      held.fetchedAt = Date.now();
      held.error = null;
      failures = 0;
    },
    stop(): void {
      disposed = true;
      stopped = true;
      if (offPush) offPush();
      if (offTopics) offTopics();
      if (timer !== undefined) clearTimeout(timer);
      timer = undefined;
      registry.delete(entry);
      if (typeof document !== 'undefined') {
        document.removeEventListener('visibilitychange', onVisible);
      }
    },
  };
}
