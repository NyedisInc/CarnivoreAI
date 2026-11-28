/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import { setLocale } from '../../../lib/i18n/index.svelte';
import { setSwarmView } from '../huddle-swarm-view.svelte';
import SwarmTitleActions from './SwarmTitleActions.svelte';

setLocale('en');

describe('SwarmTitleActions', () => {
  let app: object | null = null;
  afterEach(() => {
    if (app) unmount(app);
    app = null;
    document.body.innerHTML = '';
  });

  function draw(popout: boolean): HTMLElement {
    document.body.innerHTML = '<div id="host"></div>';
    const host = document.getElementById('host') as HTMLElement;
    app = mount(SwarmTitleActions, { target: host, props: { popout } });
    flushSync();
    return host;
  }

  test('the swarm view: the switch, the density keys and the page icon key (no text link)', () => {
    setSwarmView('swarm');
    const host = draw(false);
    expect(host.querySelectorAll('[data-huddle-swarm-view-key]').length).toBe(2);
    expect(host.querySelectorAll('[data-huddle-density-key]').length).toBe(3);
    const page = host.querySelector('[data-huddle-swarm-page]') as HTMLElement;
    expect(page.querySelector('svg')).not.toBeNull();
    expect(page.textContent?.trim()).toBe('');
  });

  test('the settings key is drawn in both views and not in the pop-out (the Home menu no longer has a huddle row)', () => {
    for (const view of ['swarm', 'lists'] as const) {
      setSwarmView(view);
      const key = draw(false).querySelector('[data-huddle-settings-page]') as HTMLElement;
      expect(key.getAttribute('aria-label')).toBe('swarm settings');
      expect(key.querySelector('svg')).not.toBeNull();
    }
    expect(draw(true).querySelector('[data-huddle-settings-page]')).toBeNull();
    setSwarmView('swarm');
  });

  test('the lists view: the switch alone', () => {
    setSwarmView('lists');
    const host = draw(false);
    expect(host.querySelectorAll('[data-huddle-swarm-view-key]').length).toBe(2);
    expect(host.querySelector('[data-huddle-density-key]')).toBeNull();
    expect(host.querySelector('[data-huddle-swarm-page]')).toBeNull();
    setSwarmView('swarm');
  });

  test('the pop-out draws nothing', () => {
    expect(draw(true).children.length).toBe(0);
  });
});
