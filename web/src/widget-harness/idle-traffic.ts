/*  hidden  */

export const IDLE_SPAN_MS = 60_000;

export interface IdleTotals {
  requests: number;
  bytes: number;
}

export interface IdleCounter extends IdleTotals {
  record(bytes: number): void;
}

export interface TimerHost {
  setTimeout: (...args: any[]) => any;
  setInterval: (...args: any[]) => any;
  clearTimeout: (id: any) => void;
  clearInterval: (id: any) => void;
}

export interface VirtualClock {
  now(): number;
  advance(ms: number): Promise<void>;
  restore(): void;
}

interface Pending {
  id: number;
  at: number;
  every: number | null;
  run: () => void;
}

export function newIdleCounter(): IdleCounter {
  const counter: IdleCounter = {
    requests: 0,
    bytes: 0,
    record(bytes: number): void {
      counter.requests += 1;
      counter.bytes += bytes;
    },
  };
  return counter;
}

export interface LiveTimer {
  id: unknown;
  fn: unknown;
  delay: unknown;
  every: boolean;
  args: unknown[];
}

export interface TimerTracker {
  stop(): LiveTimer[];
}

export function trackTimers(target: TimerHost): TimerTracker {
  const real = { setTimeout: target.setTimeout, setInterval: target.setInterval, clearTimeout: target.clearTimeout, clearInterval: target.clearInterval };
  const live = new Map<unknown, LiveTimer>();
  const watch = (start: (...a: any[]) => any, every: boolean) => (fn: unknown, delay?: unknown, ...args: unknown[]) => {
    const wrapped = every ? fn : typeof fn === 'function' ? (...a: unknown[]) => { live.delete(id); (fn as (...x: unknown[]) => void)(...a); } : fn;
    const id = start.call(target, wrapped, delay, ...args);
    live.set(id, { id, fn, delay, every, args });
    return id;
  };
  const forget = (clear: (id: any) => void) => (id: unknown) => {
    live.delete(id);
    clear.call(target, id);
  };
  target.setTimeout = watch(real.setTimeout, false);
  target.setInterval = watch(real.setInterval, true);
  target.clearTimeout = forget(real.clearTimeout);
  target.clearInterval = forget(real.clearInterval);
  return {
    stop(): LiveTimer[] {
      Object.assign(target, real);
      const out = [...live.entries()];
      for (const [id, timer] of out) (timer.every ? real.clearInterval : real.clearTimeout).call(target, id);
      live.clear();
      return out.map(([, timer]) => timer);
    },
  };
}

export function installVirtualTimers(target: TimerHost, adopt: readonly LiveTimer[] = []): VirtualClock {
  const real = {
    setTimeout: target.setTimeout,
    setInterval: target.setInterval,
    clearTimeout: target.clearTimeout,
    clearInterval: target.clearInterval,
  };
  let now = 0;
  let nextId = 1_000_000;
  const queue = new Map<number, Pending>();
  const add = (fn: unknown, delay: unknown, every: boolean, args: unknown[], keep?: number): number => {
    const wait = Math.max(0, Number(delay) || 0);
    const id = keep ?? nextId++;
    const run = typeof fn === 'function' ? () => (fn as (...a: unknown[]) => void)(...args) : () => undefined;
    queue.set(id, { id, at: now + wait, every: every ? Math.max(1, wait) : null, run });
    return id;
  };
  for (const timer of adopt) {
    const held = Number(timer.id);
    add(timer.fn, timer.delay, timer.every, timer.args, Number.isInteger(held) && held > 0 && held < 1_000_000 ? held : undefined);
  }
  target.setTimeout = (fn: unknown, delay?: unknown, ...args: unknown[]) => add(fn, delay, false, args);
  target.setInterval = (fn: unknown, delay?: unknown, ...args: unknown[]) => add(fn, delay, true, args);
  target.clearTimeout = (id: unknown) => void queue.delete(Number(id));
  target.clearInterval = (id: unknown) => void queue.delete(Number(id));
  const settle = (): Promise<void> => new Promise((resolve) => real.setTimeout.call(target, resolve, 0));
  return {
    now: () => now,
    async advance(ms: number): Promise<void> {
      const end = now + ms;
      for (;;) {
        const due = [...queue.values()].filter((t) => t.at <= end).sort((a, b) => a.at - b.at || a.id - b.id)[0];
        if (!due) break;
        now = due.at;
        if (due.every === null) queue.delete(due.id);
        else due.at += due.every;
        due.run();
        await settle();
      }
      now = end;
    },
    restore(): void {
      Object.assign(target, real);
    },
  };
}

export async function measureIdleMinute(clock: VirtualClock, counter: IdleCounter, ms: number = IDLE_SPAN_MS): Promise<IdleTotals> {
  const before = { requests: counter.requests, bytes: counter.bytes };
  await clock.advance(ms);
  return { requests: counter.requests - before.requests, bytes: counter.bytes - before.bytes };
}

export interface IdleReport {
  shown: IdleTotals;
  hidden: IdleTotals;
}

/*  hidden  */
export function idleVerdict(report: IdleReport): string[] {
  if (report.hidden.requests === 0 && report.hidden.bytes === 0) return [];
  return [`hidden widget sent ${report.hidden.requests} request(s), ${report.hidden.bytes} byte(s) in a simulated minute (must be 0)`];
}
