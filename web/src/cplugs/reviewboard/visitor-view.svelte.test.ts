/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { flushSync, tick } from 'svelte';
import { SvelteMap } from 'svelte/reactivity';
import { openVisitorRevision, registerVisitorRevisionSource, resetVisitorRevisions, type VisitorAnswerBody, type VisitorRevision } from './board-visitor-revisions.svelte';
import { revision as boardRevision } from './fixtures';
import { VisitorView, type VisitorFrame } from './visitor-view.svelte';

const U1: VisitorRevision = { label: 'u1', number: 1, revision: 'r1', updated_at: 1 };
const stops: Array<() => void> = [];

function makeView(): VisitorView {
  let view: VisitorView | null = null;
  stops.push($effect.root(() => { view = new VisitorView(); }));
  return view!;
}

function source(id = 'test.visitors'): { live: SvelteMap<number, VisitorRevision>; asked: string[]; follow: ReturnType<typeof vi.fn>; stop: ReturnType<typeof vi.fn> } {
  const live = new SvelteMap<number, VisitorRevision>();
  const asked: string[] = [];
  const stop = vi.fn();
  const follow = vi.fn((slug: string) => ({
    rows: () => [...live.values()], stop,
    answers: async (revision: string, number: number): Promise<VisitorAnswerBody | null> => {
      asked.push(`${slug}:${revision}:u${number}:${live.get(number)?.updated_at}`);
      return { answers: [{ prompt: 'layout', text: `edit ${live.get(number)?.updated_at}` }] };
    },
  }));
  registerVisitorRevisionSource({ id, enabled: () => true, follow });
  return { live, asked, follow, stop };
}

async function settle(): Promise<void> {
  for (let i = 0; i < 4; i += 1) { flushSync(); await tick(); await Promise.resolve(); }
}

afterEach(() => { while (stops.length) stops.pop()!(); resetVisitorRevisions(); });

describe('following the sources', () => {
  it('follows a source that registers after the page started following its board', async () => {
    const view = makeView();
    view.follow('nav');
    await settle();
    const { live, follow } = source();
    live.set(1, U1);
    await settle();
    expect(follow).toHaveBeenCalledWith('nav');
    expect(view.of('r1').map((row) => row.label)).toEqual(['u1']);
  });

  it('drops the follow on another board and when stopped', async () => {
    const { follow, stop } = source();
    const view = makeView();
    view.follow('nav');
    await settle();
    view.follow('other');
    await settle();
    expect(follow).toHaveBeenLastCalledWith('other');
    expect(stop).toHaveBeenCalledTimes(1);
    view.stop();
    await settle();
    expect(stop).toHaveBeenCalledTimes(2);
  });
});

describe('the opener', () => {
  it('giving it back leaves the other open board page\'s opener in place', () => {
    const first = vi.fn();
    const second = vi.fn();
    const giveFirst = makeView().claimOpener(first);
    makeView().claimOpener(second);
    giveFirst();
    expect(openVisitorRevision('nav', 'r1', 1)).toBe(true);
    expect([first.mock.calls.length, second.mock.calls.length]).toEqual([0, 1]);
  });
});

describe('the body of the u-revision on show', () => {
  it('is read from its source when opened, and read again when the visitor edits', async () => {
    const { live, asked } = source();
    live.set(1, U1);
    const view = makeView();
    view.follow('nav');
    view.select('r1', 1);
    await settle();
    expect(view.shown?.body).toEqual({ answers: [{ prompt: 'layout', text: 'edit 1' }] });
    live.set(1, { ...U1, updated_at: 2 });
    await settle();
    expect(view.shown?.body).toEqual({ answers: [{ prompt: 'layout', text: 'edit 2' }] });
    expect(asked).toEqual(['nav:r1:u1:1', 'nav:r1:u1:2']);
  });

  it('is read again when the visitor edits twice inside the same second (the listing reports a new print, not a new time)', async () => {
    const { live, asked } = source();
    live.set(1, { ...U1, print: 'aaaa1111' });
    const view = makeView();
    view.follow('nav');
    view.select('r1', 1);
    await settle();
    live.set(1, { ...U1, print: 'bbbb2222' });
    await settle();
    expect(asked).toHaveLength(2);
  });

  it('is not read again when another visitor edits (the shown row did not move)', async () => {
    const { live, asked } = source();
    live.set(1, { ...U1, print: 'aaaa1111' });
    const view = makeView();
    view.follow('nav');
    view.select('r1', 1);
    await settle();
    live.set(2, { label: 'u2', number: 2, revision: 'r1', updated_at: 5, print: 'cccc3333' });
    await settle();
    expect(asked).toHaveLength(1);
  });
});

describe('a layer or payload page', () => {
  it('shows the visitor\'s payload read only, again after the frame reloads, and hands back the owner\'s when hidden', async () => {
    const { live } = source();
    live.set(1, U1);
    const calls: string[] = [];
    const frame: VisitorFrame = { load: (payload, save) => calls.push(`load ${JSON.stringify(payload)} ${save}`), readOnly: (on) => calls.push(`readonly ${on}`) };
    const page = boardRevision(1, { payload_mode: true, prompts: [] });
    const owner = vi.fn();
    let view: VisitorView | null = null;
    stops.push($effect.root(() => {
      view = new VisitorView();
      view.bindFrame(() => page, () => frame, owner);
    }));
    const v = view!;
    registerVisitorRevisionSource({ id: 'test.visitors', enabled: () => true, follow: () => ({
      rows: () => [...live.values()], stop: () => undefined, answers: async () => ({ payload: { pick: 'b' } }),
    }) });
    v.follow('nav');
    v.select('r1', 1);
    await settle();
    expect(calls).toEqual(['readonly true', 'load {"pick":"b"} null']);
    expect(v.frameReady(frame)).toBe(true);
    v.select(null, null);
    await settle();
    expect(calls.slice(-1)).toEqual(['readonly false']);
    expect(owner).toHaveBeenCalledWith(page);
    expect(v.frameReady(frame)).toBe(false);
  });
});

describe('a failed read of the u-revision on show (review round 2)', () => {
  it('is caught and kept on the view, keeps the last good answers, and a later good read clears it', async () => {
    const live = new SvelteMap<number, VisitorRevision>([[1, U1]]);
    let fail = false;
    registerVisitorRevisionSource({ id: 'test.visitors', enabled: () => true, follow: () => ({
      rows: () => [...live.values()], stop: () => undefined,
      answers: async (): Promise<VisitorAnswerBody | null> => {
        if (fail) throw new Error('503');
        return { answers: [{ prompt: 'layout', text: 'good' }] };
      },
    }) });
    const view = makeView();
    view.follow('nav');
    view.select('r1', 1);
    await settle();
    fail = true;
    live.set(1, { ...U1, updated_at: 2 });
    await settle();
    expect(view.readFailed).toBe(true);
    expect(view.shown?.body).toEqual({ answers: [{ prompt: 'layout', text: 'good' }] });
    fail = false;
    live.set(1, { ...U1, updated_at: 3 });
    await settle();
    expect(view.readFailed).toBe(false);
  });
});
