/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

vi.mock('../api', () => ({
  isDemo: () => false,
  sessions: { status: 'idle', data: null },
  transport: { state: 'unknown' },
}));

import TopBar from './TopBar.svelte';
import { viewport } from '../engine/viewport.svelte';

const SOURCE = fs.readFileSync(path.join(process.cwd(), 'src/opscenter/shell/TopBar.svelte'), 'utf8');

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
  viewport.wide = true;
  viewport.phone = false;
});

function render(): HTMLElement {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(TopBar, { target, props: {} }));
  flushSync();
  return target;
}

describe('the dead bell and avatar are gone; there is no gear', () => {
  test('the dead bell and the inert avatar are not drawn at any width (#1157)', () => {
    for (const phone of [false, true]) {
      viewport.wide = !phone;
      viewport.phone = phone;
      const bar = render();
      expect(bar.querySelector('.oc-topbar-bell'), 'dead bell drawn').toBeNull();
      expect(bar.querySelector('.oc-topbar-avatar'), 'inert avatar drawn').toBeNull();
      expect(bar.querySelector('.oc-topbar-agents'), 'session count drawn').toBeNull();
    }
  });

  test('no gear icon exists at desktop width', () => {
    viewport.wide = true;
    viewport.phone = false;
    const bar = render();
    expect(bar.querySelector('[aria-label="Settings"]')).toBeNull();
    expect(bar.querySelector('.oc-tune')).toBeNull();
  });

  test('no gear icon exists at phone width', () => {
    viewport.wide = false;
    viewport.phone = true;
    const bar = render();
    expect(bar.querySelector('[aria-label="Settings"]')).toBeNull();
    expect(bar.querySelector('.oc-tune')).toBeNull();
  });

  test('the source carries no trace of TunePopover or the tune module', () => {
    expect(SOURCE).not.toMatch(/TunePopover/);
    expect(SOURCE).not.toMatch(/tune\.svelte/);
    expect(SOURCE).not.toMatch(/name="gear"/);
  });
});
