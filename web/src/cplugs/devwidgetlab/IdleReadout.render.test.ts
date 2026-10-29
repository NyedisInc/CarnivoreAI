/** @vitest-environment jsdom */
import { afterEach, describe, expect, it } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import IdleReadout from './IdleReadout.svelte';
import { setLocale } from '../../lib/i18n/index.svelte';

setLocale('en');

let app: ReturnType<typeof mount> | null = null;
afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

describe('IdleReadout', () => {
  it('mounts no frame until pressed, then one hidden idle=1 frame that never waits for a scenario', async () => {
    const spec = { widget: 'core.notes', host: 'home', size: 'm', theme: 'carnivore', fixture: 'data' as const, scenario: true };
    app = mount(IdleReadout, { target: document.body, props: { spec, size: { name: 'm', w: 384, h: 256, viewport: 1600, declared: false, floor: false } } });
    flushSync();
    expect(document.querySelector('iframe')).toBeNull();
    document.querySelector<HTMLButtonElement>('[data-idle-run]')!.click();
    await tick();
    flushSync();
    const frame = document.querySelector('iframe')!;
    const query = new URL(frame.src, 'http://x.test').searchParams;
    expect(query.get('idle')).toBe('1');
    expect(query.get('scenario')).toBeNull();
    expect(frame.getAttribute('aria-hidden')).toBe('true');
  });
});
