/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import PageFrame from './PageFrame.svelte';
import { APP_SANDBOX, ARTIFACT_SANDBOX, frameable } from './page-frame';

const ARTIFACT = { key: 'huddle_artifact:395:0a1b2c3d', src: '/api/v1/cplugs/huddle/artifact-view/1.0a1b2c3d.9.sig', frame: 'sandboxed' as const, title: 'Layout A' };
const FLOW = { key: 'app:/static/popout.html?tab=flow&item=1', src: '/static/popout.html?tab=flow&item=1', frame: 'app' as const, title: 'flow' };

let app: ReturnType<typeof mount> | null = null;
function show(page: unknown): HTMLElement {
  const target = document.createElement('div');
  document.body.appendChild(target);
  app = mount(PageFrame, { target, props: { page: page as never } });
  flushSync();
  return target;
}

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

describe('the page frame', () => {
  test("an artifact gets the dialog's locked-down frame", () => {
    const frame = show(ARTIFACT).querySelector('iframe') as HTMLIFrameElement;
    expect(frame.getAttribute('sandbox')).toBe(ARTIFACT_SANDBOX);
    expect(frame.getAttribute('sandbox')).not.toContain('allow-same-origin');
    expect(frame.getAttribute('referrerpolicy')).toBe('no-referrer');
    expect(frame.getAttribute('src')).toBe(ARTIFACT.src);
    expect(frame.getAttribute('title')).toBe('Layout A');
  });

  test('a pop-out path gets a same-origin frame with exactly the app sandbox', () => {
    const frame = show(FLOW).querySelector('[data-page-frame="app"]') as HTMLIFrameElement;
    expect(frame.getAttribute('sandbox')).toBe(APP_SANDBOX);
    expect(APP_SANDBOX).not.toMatch(/allow-top-navigation/);
    expect(frame.getAttribute('src')).toBe(FLOW.src);
  });

  test('the literal sandboxes in the component are the documented ones', () => {
    const svelte = fs.readFileSync(path.resolve(__dirname, 'PageFrame.svelte'), 'utf8');
    expect(svelte).toContain(`sandbox="${APP_SANDBOX}"`);
    expect(svelte).toContain(`sandbox="${ARTIFACT_SANDBOX}"`);
  });

  test.each([
    [{ ...FLOW, src: 'https://evil.example/static/popout.html' }],
    [{ ...FLOW, src: '//evil.example/static/popout.html' }],
    [{ ...FLOW, src: '/static/index.html' }],
    [{ ...FLOW, src: '/static/popout.html\\..\\index.html' }],
    [{ ...ARTIFACT, src: '/static/popout.html' }],
    [{ ...ARTIFACT, src: null }],
    [{ ...ARTIFACT, frame: 'top' }],
    [null],
  ])('a page that cannot be framed mounts nothing and says so: %j', (page) => {
    expect(frameable(page)).toBeNull();
    const target = show(page ?? { key: '', src: null, frame: 'app', title: '' });
    expect(target.querySelector('iframe')).toBeNull();
    expect(target.querySelector('[data-page-frame-unavailable]')).not.toBeNull();
  });
});
