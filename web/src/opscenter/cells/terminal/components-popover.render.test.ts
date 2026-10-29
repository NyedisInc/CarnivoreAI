/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import ComponentsPopover from '../../engine/ComponentsPopover.svelte';
import { terminalLayout, homeLayout } from '../../engine/layout.svelte';
import { layoutEditor } from '../../layout-editor/editor.svelte';
import { viewport } from '../../engine/viewport.svelte';

function page(): { host: HTMLElement; anchor: HTMLElement } {
  document.body.innerHTML =
    '<button id="kebab" type="button">more</button><div id="terminal-components"></div>';
  return {
    host: document.getElementById('terminal-components') as HTMLElement,
    anchor: document.getElementById('kebab') as HTMLElement,
  };
}

function open(host: HTMLElement, anchor: HTMLElement, onClose: () => void) {
  const app = mount(ComponentsPopover, {
    target: host,
    props: { anchor, store: terminalLayout, onClose },
  });
  flushSync();
  return app;
}

afterEach(() => {
  document.body.innerHTML = '';
});

describe('the list the terminal page opens is the engine\'s own', () => {
  test('it opens anchored, carrying no add or per-mode arrange any more (issue #1043)', () => {
    const { host, anchor } = page();
    const app = open(host, anchor, () => {});

    const panel = host.querySelector('.oc-popover') as HTMLElement;
    expect(panel).not.toBe(null);
    expect(panel.getAttribute('role')).toBe('dialog');

    const items = Array.from(host.querySelectorAll('button')).map((b) => (b.textContent || '').trim());
    expect(items.some((text) => /add/i.test(text))).toBe(false);
    expect(items.filter((text) => /^arrange in /i.test(text)).length).toBe(0);
    expect(items.some((text) => text === 'arrange layout')).toBe(true);
    expect(items.some((text) => /reset/i.test(text))).toBe(true);
    expect(items.some((text) => /fit rows/i.test(text))).toBe(false);
    expect(items.some((text) => /all widgets/i.test(text))).toBe(true);
    for (const hidden of [/notes/i, /files/i, /scheduled tasks/i, /keep awake/i]) {
      expect(items.some((text) => hidden.test(text))).toBe(false);
    }
    expect(host.querySelector('[data-layout-editor-pointer]')?.textContent).toBe(
      'add widgets in edit layout, bottom left of the drawer',
    );
    expect(items.length).toBe(3);

    unmount(app, { outro: false });
    flushSync();
    expect(host.querySelector('.oc-popover')).toBe(null);
  });

  test('"arrange layout" opens edit mode instead of touching either layout directly', () => {
    const { host, anchor } = page();
    const beforeHome = JSON.stringify(homeLayout.state.layout);
    const beforeTerminal = JSON.stringify(terminalLayout.state.layout);
    const app = open(host, anchor, () => {});

    const arrange = Array.from(host.querySelectorAll('button'))
      .find((b) => (b.textContent || '').trim() === 'arrange layout') as HTMLButtonElement;
    expect(arrange).not.toBe(undefined);
    arrange.click();
    flushSync();
    expect(layoutEditor.active).toBe(false);
    expect(JSON.stringify(terminalLayout.state.layout)).toBe(beforeTerminal);
    expect(JSON.stringify(homeLayout.state.layout)).toBe(beforeHome);

    unmount(app, { outro: false });
    flushSync();
  });
});

describe('every route closes it', () => {
  test('escape asks its owner to close and puts focus back on the anchor', () => {
    const { host, anchor } = page();
    let closed = 0;
    const app = open(host, anchor, () => {
      closed += 1;
    });
    expect(host.querySelector('.oc-popover')).not.toBe(null);

    const panel = host.querySelector('.oc-popover') as HTMLElement;
    panel.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    flushSync();
    expect(closed).toBe(1);
    expect(document.activeElement).toBe(anchor);

    unmount(app, { outro: false });
    flushSync();
  });

  test('a pointer outside it asks its owner to close; one inside does not', () => {
    const { host, anchor } = page();
    let closed = 0;
    const app = open(host, anchor, () => {
      closed += 1;
    });

    const panel = host.querySelector('.oc-popover') as HTMLElement;
    panel.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
    flushSync();
    expect(closed).toBe(0);

    document.body.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
    flushSync();
    expect(closed).toBe(1);

    unmount(app, { outro: false });
    flushSync();
  });

  test('unmounting takes it off screen whatever it was showing', () => {
    const { host, anchor } = page();
    const app = open(host, anchor, () => {});
    expect(host.querySelectorAll('button').length).toBe(3);
    unmount(app, { outro: false });
    flushSync();
    expect(host.querySelectorAll('button').length).toBe(0);
    expect(host.childElementCount).toBe(0);
  });
});

describe('below 1024 the restore list is the phone\'s show and hide, unchanged (issue #725)', () => {
  test('every hidden widget is a restore row again, and no pointer line', () => {
    viewport.wide = false;
    viewport.phone = true;
    try {
      const { host, anchor } = page();
      const app = open(host, anchor, () => {});
      const items = Array.from(host.querySelectorAll('button')).map((b) => (b.textContent || '').trim());
      for (const hidden of [/notes/i, /files/i, /scheduled tasks/i, /keep awake/i]) {
        expect(items.some((text) => hidden.test(text))).toBe(true);
      }
      expect(host.querySelector('[data-layout-editor-pointer]')).toBe(null);
      unmount(app, { outro: false });
      flushSync();
    } finally {
      viewport.wide = true;
      viewport.phone = false;
    }
  });
});
