/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const fake = vi.hoisted(() => ({ git: null as unknown, held: [] as string[], released: [] as string[], session: 'ses_1', onScreen: true }));

vi.mock('../../lib/active-terminal', () => ({ activeTerminalSessionId: () => fake.session }));
vi.mock('../../api/session-git.svelte', () => ({
  sessionGit: (id: string) => {
    fake.held.push(id);
    return { data: fake.git };
  },
  releaseSessionGit: (id: string) => void fake.released.push(id),
}));
vi.mock('./on-screen', () => ({ watchOnScreen: (_node: Element, set: (yes: boolean) => void) => { set(fake.onScreen); return () => {}; } }));

import FilesGlanceTile from './FilesGlanceTile.svelte';
import { setLocale } from '../../../lib/i18n/index.svelte';

setLocale('en');

let app: ReturnType<typeof mount> | null = null;
afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
  Object.assign(fake, { git: null, held: [], released: [], session: 'ses_1', onScreen: true });
});

function draw(): HTMLElement {
  app = mount(FilesGlanceTile, { target: document.body, props: { onopen: () => {} } });
  flushSync();
  return document.querySelector<HTMLElement>('[data-files-glance]')!;
}

describe('files glance tile', () => {
  test('says changed N for a repo with changes (mutation: read the count from the wrong field)', () => {
    fake.git = { state: 'ok', files: [{}, {}], truncated: 3, repo_name: 'api', branch: 'main', counts: {}, read_at: 1 };
    expect(draw().textContent?.trim()).toBe('changed 5');
  });

  test('says the widget name, never clean, before the read lands', () => {
    expect(draw().textContent?.trim()).toBe('files');
  });

  test('holds the session read while shown and releases it when it goes (mutation: skip the release)', () => {
    draw();
    expect(fake.held).toEqual(['ses_1']);
    unmount(app!);
    app = null;
    expect(fake.released).toEqual(['ses_1']);
  });

  test('asks for nothing while not on screen', () => {
    fake.onScreen = false;
    draw();
    expect(fake.held).toEqual([]);
  });
});
