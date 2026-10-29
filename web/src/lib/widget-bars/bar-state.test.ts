import { describe, expect, test } from 'vitest';
import {
  PeekController, RETRACT_MS, barOut, barState, foldedEdge, inFlow, peekOut, showsHandle,
  type BarStateInput, type Clock, type PeekFlags,
} from './bar-state';

function fakeClock(): Clock & { tick(ms: number): void; pending(): number } {
  let now = 0;
  let next = 1;
  const timers = new Map<number, { at: number; fn: () => void }>();
  return {
    setTimeout(fn, ms) {
      const id = next++;
      timers.set(id, { at: now + ms, fn });
      return id;
    },
    clearTimeout(handle) {
      timers.delete(handle as number);
    },
    tick(ms) {
      now += ms;
      for (const [id, timer] of [...timers]) if (timer.at <= now) { timers.delete(id); timer.fn(); }
    },
    pending: () => timers.size,
  };
}

const base: BarStateInput = {
  show: true, drawn: true, editing: false, folded: false, panelShown: false, mode: 'autohide',
  hover: false, focusIn: false, touchPeek: false, retracting: false,
};
const at = (patch: Partial<BarStateInput>) => barState({ ...base, ...patch });

function peekWith(clock: Clock): { peek: PeekController; seen: PeekFlags } {
  const seen: PeekFlags = { hover: false, focusIn: false, touchPeek: false, retracting: false };
  return { peek: new PeekController(clock, (flags) => Object.assign(seen, flags)), seen };
}

describe('the 4.1 state table, first match wins', () => {
  test('absent, edit, folded, held, pinned, peek, handle', () => {
    expect(at({ show: false })).toBe('absent');
    expect(at({ drawn: false })).toBe('absent');
    expect(at({ drawn: false, editing: true })).toBe('edit');
    expect(at({ editing: true, mode: 'pinned', hover: true })).toBe('edit');
    expect(at({ folded: true })).toBe('folded');
    expect(at({ folded: true, hover: true })).toBe('peek');
    expect(at({ panelShown: true, mode: 'pinned' })).toBe('held');
    expect(at({ mode: 'pinned' })).toBe('pinned');
    expect(at({ mode: 'pinned', hover: true })).toBe('pinned');
    for (const flag of ['hover', 'focusIn', 'touchPeek', 'retracting'] as const) expect(at({ [flag]: true })).toBe('peek');
    expect(at({})).toBe('handle');
  });

  test('a panel shown holds the bar in flow whatever else holds it out', () => {
    expect(at({ panelShown: true })).toBe('held');
    expect(at({ panelShown: true, hover: true, retracting: true })).toBe('held');
    expect(at({ panelShown: true, folded: true })).toBe('folded');
  });

  test('which states take the grid track, draw the layer and the handle (no state draws a pin icon)', () => {
    const rows = { absent: [false, false, false], edit: [true, true, false], folded: [false, false, true],
      held: [true, true, false], pinned: [true, true, false], peek: [false, true, true], handle: [false, false, true] } as const;
    for (const [state, [flow, out, handle]] of Object.entries(rows)) {
      const s = state as keyof typeof rows;
      expect([inFlow(s), barOut(s), showsHandle(s)]).toEqual([flow, out, handle]);
    }
  });

  test('one at a time folds only the bar the other edge leads', () => {
    expect(foldedEdge('one', 'bottom', 'side')).toBe(true);
    expect(foldedEdge('one', 'side', 'side')).toBe(false);
    expect(foldedEdge('one', null, 'side')).toBe(false);
    expect(foldedEdge('both', 'bottom', 'side')).toBe(false);
  });
});

describe('the 4.2 transitions', () => {
  test('a pointer over a closed bar opens it at once, and leaving arms the retract', () => {
    const clock = fakeClock();
    const { peek, seen } = peekWith(clock);
    peek.enter();
    expect(barState({ ...base, ...seen })).toBe('peek');
    expect(peekOut(peek.flags)).toBe(true);
    peek.leave();
    expect(clock.pending()).toBe(1);
    clock.tick(RETRACT_MS);
    expect(barState({ ...base, ...seen })).toBe('handle');
  });

  test('a click is out at once; pointer out retracts at 300 ms, not 299', () => {
    const clock = fakeClock();
    const { peek, seen } = peekWith(clock);
    expect(clock.pending()).toBe(0);
    peek.open();
    expect(barState({ ...base, ...seen })).toBe('peek');
    peek.leave();
    clock.tick(RETRACT_MS - 1);
    expect(barState({ ...base, ...seen })).toBe('peek');
    clock.tick(1);
    expect(barState({ ...base, ...seen })).toBe('handle');
    expect(clock.pending()).toBe(0);
  });

  test('pointer back in during the wait cancels the retract', () => {
    const clock = fakeClock();
    const { peek, seen } = peekWith(clock);
    peek.open();
    peek.leave();
    clock.tick(200);
    peek.enter();
    clock.tick(1000);
    expect(seen.hover).toBe(true);
    expect(barState({ ...base, ...seen })).toBe('peek');
  });

  test('focus inside holds the bar out; focus leaving retracts it; the pointer still over holds it', () => {
    const clock = fakeClock();
    const { peek, seen } = peekWith(clock);
    peek.focusIn();
    peek.enter();
    peek.leave();
    clock.tick(5000);
    expect(barState({ ...base, ...seen })).toBe('peek');
    peek.enter();
    peek.focusOut();
    clock.tick(5000);
    expect(barState({ ...base, ...seen })).toBe('peek');
    peek.leave();
    clock.tick(RETRACT_MS);
    expect(barState({ ...base, ...seen })).toBe('handle');
  });

  test('a panel open never retracts (held), and its closing starts the 300 ms wait', () => {
    const clock = fakeClock();
    const { peek, seen } = peekWith(clock);
    peek.open();
    peek.leave();
    clock.tick(RETRACT_MS);
    expect(at({ ...seen, panelShown: true })).toBe('held');
    peek.panelClosed();
    expect(at({ ...seen })).toBe('peek');
    clock.tick(RETRACT_MS - 1);
    expect(at({ ...seen })).toBe('peek');
    clock.tick(1);
    expect(at({ ...seen })).toBe('handle');
  });

  test('a panel closing while hovered or focused leaves the bar peeking with no timer', () => {
    const clock = fakeClock();
    const { peek, seen } = peekWith(clock);
    peek.open();
    peek.panelClosed();
    expect(clock.pending()).toBe(0);
    expect(at({ ...seen })).toBe('peek');
  });

  test('Escape retracts at once whatever held the bar out', () => {
    const clock = fakeClock();
    const { peek, seen } = peekWith(clock);
    peek.open();
    peek.focusIn();
    peek.tap();
    peek.escape();
    expect(barState({ ...base, ...seen })).toBe('handle');
    expect(clock.pending()).toBe(0);
  });

  test('a touch tap toggles the peek and a touch press elsewhere puts it back', () => {
    const clock = fakeClock();
    const { peek, seen } = peekWith(clock);
    peek.tap();
    expect(barState({ ...base, ...seen })).toBe('peek');
    peek.tap();
    expect(barState({ ...base, ...seen })).toBe('handle');
    peek.tap();
    peek.dismissTouch();
    expect(barState({ ...base, ...seen })).toBe('handle');
    peek.tap();
    clock.tick(10_000);
    expect(seen.touchPeek).toBe(true);
  });

  test('destroying the controller clears a pending timer', () => {
    const clock = fakeClock();
    const { peek } = peekWith(clock);
    peek.open();
    peek.leave();
    expect(clock.pending()).toBe(1);
    peek.destroy();
    expect(clock.pending()).toBe(0);
  });
});
