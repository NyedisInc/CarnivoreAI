/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const fake = vi.hoisted(() => ({ answers: [] as unknown[] }));

vi.mock('../../api/auth.svelte', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  authFetch: () => Promise.resolve(fake.answers.shift() ?? { status: 'unchanged', body: '', revision: 0, updated_at: null }),
}));
vi.mock('../../api/events.svelte', async (importOriginal) => ({ ...(await importOriginal<Record<string, unknown>>()), subscribe: () => () => {} }));
vi.mock('../../api/host', async (importOriginal) => ({ ...(await importOriginal<Record<string, unknown>>()), primarySessionId: () => 'ses_1' }));
vi.mock('../../api', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  primarySessionId: () => 'ses_1',
  sessions: { get data() { return [{ session: { id: 'ses_1' }, tmux_session: 'cloude_api' }]; } },
}));

import PlacementBody from '../../../lib/zone-shell/PlacementBody.svelte';
import { allocateLetters } from '../../../lib/widget-bars/pinned-scope';
import NotesCell from './Cell.svelte';
import { META } from '../../engine/meta';
import { reset } from '../../api/notes.svelte';
import { sizes } from '../../engine/observe.svelte';
import { OPEN_FOCUS } from '../../shell/open-focus.svelte';
import { CORE_MANIFESTS, coreWidgetId } from '../../widgets/core-manifests';

const apps: object[] = [];
beforeEach(() => {
  vi.stubGlobal('ResizeObserver', class { observe(): void {} unobserve(): void {} disconnect(): void {} });
});
afterEach(() => {
  while (apps.length) unmount(apps.pop()!, { outro: false });
  document.body.replaceChildren();
  localStorage.clear();
  reset();
  vi.useRealTimers();
});

async function drawn(draw: (target: HTMLElement) => object): Promise<HTMLElement> {
  vi.useFakeTimers();
  fake.answers = [{ status: 'unchanged', body: 'note', revision: 1, updated_at: '2026-10-13T12:00:00+00:00' }];
  const target = document.createElement('div');
  document.body.appendChild(target);
  apps.push(draw(target));
  flushSync();
  await vi.advanceTimersByTimeAsync(0);
  flushSync();
  return target;
}

const notes = () => {
  const manifest = CORE_MANIFESTS[coreWidgetId('notes')];
  if (!manifest) throw new Error('no core notes manifest');
  return manifest;
};

const cellProps = { width: 400, height: 400, meta: META.notes, instance: 'notes', scope: { sessionId: 'ses_1', rowId: 7, workingDir: '', projectId: null } };

describe('a widget in a bar slide-out has no title bar', () => {
  test('the slide-out draws none by default and the same widget in a drawer card keeps it', async () => {
    const manifest = notes();
    sizes[`session-rail:${manifest.id}`] = { width: 480, height: 400 };
    const rail = await drawn((el) => mount(PlacementBody, { target: el, props: { host: 'rail', manifest, pinRowId: null } }));
    expect(rail.querySelector('[data-rail-body]')).not.toBeNull();
    expect(rail.querySelector('[data-widget-head]')).toBeNull();
    sizes[`drawer-zone:${manifest.id}`] = { width: 320, height: 400 };
    const card = await drawn((el) => mount(PlacementBody, { target: el, props: { host: 'drawer', manifest } }));
    expect(card.querySelector('[data-widget-head]')).not.toBeNull();
  });
});

describe('the notes widget in a slide-out', () => {
  test('header off: no control in the body (edit, preview and save are menu items); no empty-state block', async () => {
    const manifest = notes();
    sizes[`session-rail:${manifest.id}`] = { width: 480, height: 400 };
    const rail = await drawn((el) => mount(PlacementBody, { target: el, props: { host: 'rail', manifest, pinRowId: null } }));
    expect(rail.querySelector('[data-notes-controls], [data-notes-toggle]')).toBeNull();
    expect(rail.querySelector('[data-notes-mode], [data-notes-save], [data-notes-empty], [data-notes-label]')).toBeNull();
    expect(rail.querySelector('textarea')).not.toBeNull();
  });

  test('an empty note is just the text area', async () => {
    const target = await drawn((el) => mount(NotesCell, { target: el, props: cellProps }));
    expect(target.querySelector('[data-notes-empty]')).toBeNull();
    expect(target.querySelector('textarea')?.getAttribute('placeholder')).toBeNull();
  });

  test('the caret goes into the text area, at the end, on a user open, and a plain mount never takes focus', async () => {
    const plain = await drawn((el) => mount(NotesCell, { target: el, props: cellProps }));
    expect(document.activeElement).not.toBe(plain.querySelector('textarea'));
    unmount(apps.pop()!, { outro: false });
    document.body.replaceChildren();
    reset();
    const ask = { pending: true };
    const opened = await drawn((el) => mount(NotesCell, { target: el, props: cellProps, context: new Map([[OPEN_FOCUS, ask]]) }));
    const box = opened.querySelector('textarea')!;
    expect(document.activeElement).toBe(box);
    expect(box.selectionStart).toBe(box.value.length);
    expect(ask.pending).toBe(false);
  });
});

describe('the letter on a pinned key', () => {
  test('letters are unique and stay put while an agent stays pinned', () => {
    const arbor = { row: 1, name: 'Arbor' };
    const alpha = { row: 2, name: 'Alpha' };
    const both = allocateLetters(new Map(), [arbor, alpha]);
    expect([both.get(1), both.get(2)]).toEqual(['A', 'L']);
    const afterRemove = allocateLetters(both, [alpha]);
    expect(afterRemove.get(2)).toBe('L');
    const again = allocateLetters(afterRemove, [alpha, arbor]);
    expect([again.get(1), again.get(2)]).toEqual(['A', 'L']);
    const crowd = allocateLetters(new Map(), [{ row: 1, name: 'a' }, { row: 2, name: 'a' }, { row: 3, name: 'a' }]);
    expect(new Set(crowd.values()).size).toBe(3);
    expect(allocateLetters(new Map(), [{ row: 9, name: '' }]).size).toBe(0);
  });
});
