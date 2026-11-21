/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { createRawSnippet, flushSync, mount, unmount } from 'svelte';
import SwarmOrg from './SwarmOrg.svelte';
import { AGENTS, COMPANIES, NOW, PROJECTS, SESSIONS, rowOf } from '../style-guide/swarm-fixture';
import { buildFloor } from './floor';
import { buildTree } from './swarm-tree';

let app: Record<string, unknown> | null = null;
afterEach(() => { if (app) unmount(app); app = null; document.body.innerHTML = ''; });

function press(el: Element): void {
  const e = new Event('pointerdown', { bubbles: true });
  Object.assign(e, { button: 0, pointerId: 1, clientX: 5, clientY: 5 });
  el.dispatchEvent(e);
}

test('pointerdown on the footer toggle and zoom keys leaves the click alone; on the canvas it pans', () => {
  const capture = vi.fn();
  (HTMLElement.prototype as unknown as { setPointerCapture: unknown }).setPointerCapture = capture;
  let shown = false;
  const foot = createRawSnippet(() => ({ render: () => '<button type="button" data-test-toggle>show inactive</button>', setup: (el) => {
    el.addEventListener('click', () => { shown = !shown; });
  } }));
  app = mount(SwarmOrg, { target: document.body, props: { tree: buildTree(buildFloor({ agents: AGENTS, sessions: SESSIONS, companies: COMPANIES, projects: PROJECTS, rowOf, showInactive: false })), agents: AGENTS, now: NOW, onOpen: () => {}, foot } });
  flushSync();
  const toggle = document.querySelector('[data-test-toggle]') as HTMLElement;
  press(toggle);
  toggle.click();
  expect(shown).toBe(true);
  press(document.querySelector('[data-swarm-zoom-in]')!);
  expect(capture).not.toHaveBeenCalled();
  press(document.querySelector('.pko-stage')!);
  expect(capture).toHaveBeenCalledTimes(1);
});
