/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import ComponentsPopover from './ComponentsPopover.svelte';
import { terminalLayout } from './layout.svelte';
import { recorded, reframed, snapshot } from '../../lib/dialog-frame/goldens';

const FRAME = { addClasses: ['oc-anchored'] };

let app: ReturnType<typeof mount> | null = null;
afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

for (const placement of ['beside', 'below'] as const) {
  test(`the popover renders its recorded markup (${placement})`, () => {
    document.body.innerHTML = '<button id="kebab" type="button">more</button><div id="host"></div>';
    const anchor = document.getElementById('kebab') as HTMLElement;
    app = mount(ComponentsPopover, { target: document.getElementById('host')!, props: { anchor, store: terminalLayout, onClose: () => {}, placement } });
    flushSync();
    const now = snapshot(document.querySelector('.oc-popover')!);
    expect(now).toBe(reframed(recorded(`components-popover-${placement}`, now), FRAME));
  });
}
