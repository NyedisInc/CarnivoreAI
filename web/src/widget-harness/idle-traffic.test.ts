import { describe, expect, it } from 'vitest';
import { IDLE_SPAN_MS, idleVerdict, installVirtualTimers, measureIdleMinute, newIdleCounter, trackTimers, type TimerHost } from './idle-traffic';

function host(): TimerHost {
  return { setTimeout, setInterval, clearTimeout, clearInterval } as TimerHost;
}

function plantedPoller(target: TimerHost, send: () => void, every: number): void {
  target.setInterval(send, every);
}

function storeReader(send: () => void): void {
  send();
}

async function minute(mount: (t: TimerHost, send: () => void) => void): Promise<{ requests: number; bytes: number }> {
  const target = host();
  const counter = newIdleCounter();
  const clock = installVirtualTimers(target);
  mount(target, () => counter.record(100));
  const before = counter.requests;
  const got = await measureIdleMinute(clock, counter);
  clock.restore();
  expect(got.requests).toBe(counter.requests - before);
  return got;
}

describe('idle traffic', () => {
  it('a planted 5 second poller sends 12 requests in a simulated minute, without waiting', async () => {
    const started = Date.now();
    const got = await minute((t, send) => plantedPoller(t, send, 5000));
    expect(got).toEqual({ requests: 12, bytes: 1200 });
    expect(Date.now() - started).toBeLessThan(2000);
  });

  it('goes RED when a hidden widget polls: a planted setInterval fetch fails the verdict', async () => {
    const hidden = await minute((t, send) => plantedPoller(t, send, 5000));
    const shown = await minute((t, send) => plantedPoller(t, send, 5000));
    expect(idleVerdict({ shown, hidden }).length).toBe(1);
  });

  it('passes a widget that reads its store and sets no timer', async () => {
    const hidden = await minute((_t, send) => storeReader(send));
    expect(hidden.requests).toBe(0);
    expect(idleVerdict({ shown: hidden, hidden })).toEqual([]);
  });

  it('runs timeouts once, honors clears, and restores the real timers', async () => {
    const target = host();
    const real = target.setTimeout;
    const clock = installVirtualTimers(target);
    let ran = 0;
    target.setTimeout(() => (ran += 1), 10);
    const gone = target.setTimeout(() => (ran += 100), 10);
    target.clearTimeout(gone);
    await clock.advance(IDLE_SPAN_MS);
    expect(ran).toBe(1);
    expect(clock.now()).toBe(IDLE_SPAN_MS);
    clock.restore();
    expect(target.setTimeout).toBe(real);
  });

  it('takes over a poll the page started on the real clock before the check, and a finished timeout is not carried over', async () => {
    const target = host();
    const tracker = trackTimers(target);
    const counter = newIdleCounter();
    target.setInterval(() => counter.record(10), 20_000);
    target.setTimeout(() => counter.record(10), 1);
    await new Promise((resolve) => setTimeout(resolve, 15));
    expect(counter.requests).toBe(1);
    const clock = installVirtualTimers(target, tracker.stop());
    const got = await measureIdleMinute(clock, counter);
    clock.restore();
    expect(got.requests).toBe(3);
  });

  it('keeps a taken-over poll alive when the page clears a stale real timer id that matches no live timer', async () => {
    let next = 0;
    const target = {
      setTimeout: (fn: () => void, ms?: number) => { setTimeout(fn, ms); return ++next; },
      setInterval: () => ++next,
      clearTimeout: () => undefined,
      clearInterval: () => undefined,
    } as TimerHost;
    const tracker = trackTimers(target);
    const counter = newIdleCounter();
    const done = target.setTimeout(() => undefined, 1) as number;
    target.setInterval(() => counter.record(10), 5_000);
    await new Promise((resolve) => setTimeout(resolve, 15));
    const clock = installVirtualTimers(target, tracker.stop());
    target.clearTimeout(done);
    target.clearInterval(done);
    const got = await measureIdleMinute(clock, counter);
    clock.restore();
    expect(got.requests).toBe(12);
  });
});
