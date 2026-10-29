/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { createAsTab } from './tab-landing';

let generation = 0;
const navigated = vi.fn();
const appJs = (event: Event): void => {
  const nav = (event as CustomEvent<{ nav?: number }>).detail?.nav;
  if (nav == null || nav === generation) navigated((event as CustomEvent<{ session: { id: string } }>).detail.session.id);
};

beforeEach(() => {
  generation = 0;
  (globalThis as unknown as { NavigationGeneration: unknown }).NavigationGeneration = {
    begin: () => ++generation, current: () => generation,
    keep: (token: number) => token === generation, isCurrent: (token: number) => token === generation,
  };
  globalThis.addEventListener('session-created', appJs);
});

afterEach(() => {
  globalThis.removeEventListener('session-created', appJs);
  navigated.mockReset();
});

function created(id: string, nav: number | null): void {
  globalThis.dispatchEvent(new CustomEvent('session-created', { detail: { session: { id }, nav } }));
}

function flow(): { start: () => Promise<void>; announce: (id: string) => void; nav: () => number } {
  let nav = 0;
  let done: () => void = () => {};
  return {
    start: () => {
      nav = ++generation;
      return new Promise<void>((resolve) => (done = resolve));
    },
    announce: (id) => {
      created(id, nav);
      done();
    },
    nav: () => nav,
  };
}

test("its own flow's event lands as a tab and never navigates", async () => {
  const land = vi.fn();
  const f = flow();
  const run = createAsTab(f.start, land);
  f.announce('ses_new');
  await run;
  expect(land).toHaveBeenCalledWith('ses_new');
  expect(navigated).not.toHaveBeenCalled();
});

test('another navigation during the flow passes through, and the superseded create is left to app.js', async () => {
  const land = vi.fn();
  const f = flow();
  const run = createAsTab(f.start, land);
  const click = ++generation;
  created('ses_clicked', click);
  f.announce('ses_new');
  await run;
  expect(land).not.toHaveBeenCalled();
  expect(navigated.mock.calls).toEqual([['ses_clicked']]);
});

test('a cancelled flow disarms: a later create elsewhere navigates as usual', async () => {
  const land = vi.fn();
  await createAsTab(() => (++generation, Promise.resolve()), land);
  created('ses_later', generation);
  expect(land).not.toHaveBeenCalled();
  expect(navigated).toHaveBeenCalledTimes(1);
});

test('a flow that could not start arms nothing', async () => {
  const land = vi.fn();
  await createAsTab(() => null, land);
  created('ses_other', generation);
  expect(land).not.toHaveBeenCalled();
  expect(navigated).toHaveBeenCalledTimes(1);
});
