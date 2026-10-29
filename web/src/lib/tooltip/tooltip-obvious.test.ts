/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import { tooltipTargetFor } from './tooltip';
import SwarmOrg from '../../cplugs/huddle/swarm/SwarmOrg.svelte';
import { AGENTS, COMPANIES, NOW, PROJECTS, SESSIONS, rowOf } from '../../cplugs/huddle/style-guide/swarm-fixture';
import { buildFloor } from '../../cplugs/huddle/swarm/floor';
import { buildTree } from '../../cplugs/huddle/swarm/swarm-tree';
import { cplugEnablement } from '../../cplugs/host/enablement.svelte';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';

installPopoverPolyfill();

const mounted: ReturnType<typeof mount>[] = [];

beforeEach(() => {
  localStorage.clear();
  vi.spyOn(console, 'log').mockImplementation(() => {});
});

afterEach(async () => {
  cplugEnablement.enabled = {};
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
  vi.restoreAllMocks();
});

function fixture(html: string): Element {
  document.body.innerHTML = html;
  return document.body.firstElementChild as Element;
}

test('a useful tip still shows: a shortcut, and the full text of a clipped label', () => {
  const pin = fixture('<button title="pin to top (p)"><span>pin</span></button>');
  expect(tooltipTargetFor(pin)).toBe(pin);
  const clipped = fixture('<button title="a very long agent name"><span>a very long agent name</span></button>');
  Object.defineProperty(clipped.firstElementChild, 'scrollWidth', { value: 200 });
  Object.defineProperty(clipped.firstElementChild, 'clientWidth', { value: 80 });
  expect(tooltipTargetFor(clipped)).toBe(clipped);
  const text = fixture('<button title="copy this conversation into a new session"><span>fork</span></button>');
  expect(tooltipTargetFor(text)).toBe(text);
});

test('a tip that repeats the visible text, with or without a generic verb, is no tooltip', () => {
  const open = fixture('<button title="open SysOp"><span>SysOp</span></button>');
  expect(tooltipTargetFor(open), 'open + the visible name').toBeNull();
  const fit = fixture('<button title="fit">fit</button>');
  expect(tooltipTargetFor(fit), 'the visible label itself').toBeNull();
  const fold = fixture('<button title="unfold projects"><span>projects</span></button>');
  expect(tooltipTargetFor(fold), 'unfold + the visible name').toBeNull();
});

test('the real Swarm org chart: a filled node has no tip, a vacant seat keeps the one that says what a click does', () => {
  const tree = buildTree(buildFloor({ agents: AGENTS, sessions: SESSIONS, companies: COMPANIES, projects: PROJECTS, rowOf, showInactive: false }));
  mounted.push(mount(SwarmOrg, { target: document.body, props: { tree, agents: AGENTS, now: NOW, onOpen: () => {} } }));
  flushSync();
  const nodes = [...document.querySelectorAll<HTMLElement>('.pko-node')];
  const filled = nodes.filter((n) => !n.querySelector('.pko-seat'));
  expect(filled.length, 'the chart has filled nodes').toBeGreaterThanOrEqual(1);
  for (const n of filled) expect(tooltipTargetFor(n), `${n.dataset.swarmNode} has no hover tip`).toBeNull();
  for (const key of ['[data-swarm-zoom-in]', '[data-swarm-zoom-out]', '[data-swarm-zoom-fit]']) {
    const k = document.querySelector<HTMLElement>(key)!;
    expect(k, key).not.toBeNull();
    expect(tooltipTargetFor(k), `${key} has no hover tip`).toBeNull();
  }
});
