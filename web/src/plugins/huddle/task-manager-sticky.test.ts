/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const server = vi.hoisted(() => ({ view: 'status', colors: new Map<number, string>() }));

const mk = (id: number, list: string, status = 'open') => ({
  id, list, text: `item ${id}`, note: '', position: id, created_by: 'joe', state: 'open', kind: '', number: null,
  revision: 1, created_seq: id, seq: id, deleted: false, thread: [], unread: false, group: null, status, section: status,
});

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string) => {
      if (path === '/cplugs/huddle') return { revision: 3, settings: { view: server.view, hideCompleted: false } };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') {
        return { cursor: 0, lists: ['all', '12', '18', '21'].map((key) => ({ key, name: key === 'all' ? null : `p${key}`, project_id: key === 'all' ? null : Number(key), items: 2, open: 2, review: 0, questions: 0, claude_seq: 0, unread: 0 })) };
      }
      if (path === '/cplugs/huddle/aggregate?live_only=1') {
        const group = (list: string, id: number) => ({ list, name: `p${list}`, project_id: Number(list), revision: 1, groups: [{ id: id + 100, list, name: `g${list}`, position: 0, folded: false }],
          items: [{ ...mk(id, list), group: id + 100 }, mk(id + 1, list, 'working')] });
        return { cursor: 9, groups: [group('12', 10), group('18', 20), group('21', 30)] };
      }
      if (path === '/cplugs/huddle/lists/18?live_only=1') return { list: '18', revision: 1, cursor: 1, groups: [], items: [mk(1, '18'), mk(2, '18', 'working')] };
      if (/\/sessions$/.test(path)) return { sessions: [], default: null, reason: 'pick' };
      return {};
    },
  };
});

vi.mock('../../lib/project-colors/store.svelte', () => ({
  projectColorOf: (id: number | null) => (id === null ? null : server.colors.get(id) ?? null),
}));

import { huddle, refreshTaskManager } from './huddle.svelte';
import { refreshPrefs } from './task-manager-prefs.svelte';
import { setSectionFolded } from './task-manager-status-folds.svelte';
import { projectFoldKey } from './task-manager-status-folds.svelte';
import { AGGREGATE } from './huddle-model';
import { projectStick, sectionTop } from './task-manager-sticky';
import HuddleBody from './HuddleBody.svelte';
import { cplugEnablement } from '../host/enablement.svelte';

cplugEnablement.enabled = { huddle: true };

let app: ReturnType<typeof mount> | null = null;
async function settle(): Promise<void> {
  for (let i = 0; i < 8; i += 1) {
    await Promise.resolve();
    await tick();
  }
  flushSync();
}

async function mountBody(popout: boolean): Promise<HTMLElement> {
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(HuddleBody, { target: host, props: { popout } });
  await settle();
  return host;
}

function source(file: string): string {
  return readFileSync(new URL(file, import.meta.url), 'utf8');
}

/** The declarations of the LAST rule whose selector is exactly `selector` in a component's style block. */
function rule(file: string, selector: string): string {
  const css = (source(file).split('<style>')[1] ?? '').replace('@layer components {', '');
  const found = [...css.matchAll(/(^|\n)\s*([^{}\n]+)\{([^}]*)\}/g)].filter((m) => (m[2] as string).trim() === selector);
  return (found[found.length - 1]?.[3] as string | undefined) ?? '';
}

beforeEach(async () => {
  window.sessionStorage.clear();
  server.view = 'status';
  server.colors = new Map([[12, '#4e69ba'], [18, '#7457c2']]);
  huddle.selected = AGGREGATE;
  huddle.groups = null;
  await refreshPrefs();
  await refreshTaskManager();
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

describe('the offsets', () => {
  test('project i sits i bars from the top and the rest from the bottom; the first and last touch the edge', () => {
    expect(projectStick(0, 3)).toEqual({ top: '0px', bottom: 'calc(var(--hd-phead-h) * 2)' });
    expect(projectStick(1, 3)).toEqual({ top: 'calc(var(--hd-phead-h) * 1)', bottom: 'calc(var(--hd-phead-h) * 1)' });
    expect(projectStick(2, 3)).toEqual({ top: 'calc(var(--hd-phead-h) * 2)', bottom: '0px' });
    expect(projectStick(0, 1)).toEqual({ top: '0px', bottom: '0px' });
  });

  test('section headers stick under the bars up to and including their own project; a single list sticks at the top', () => {
    expect(sectionTop(true, 0)).toBe('calc(var(--hd-phead-h) * 1)');
    expect(sectionTop(true, 2)).toBe('calc(var(--hd-phead-h) * 3)');
    expect(sectionTop(false, 0)).toBe('0px');
  });
});

describe.each([['the sidebar', false], ['the pop-out', true]])('on screen, %s', (_name, popout) => {
  test('every project bar carries its stack offsets, in list order, and a folded project keeps its bar and loses its block', async () => {
    const host = await mountBody(popout);
    const bars = [...host.querySelectorAll<HTMLElement>('.hd-group')];
    expect(bars.map((b) => b.style.getPropertyValue('--_top'))).toEqual(['0px', 'calc(var(--hd-phead-h) * 1)', 'calc(var(--hd-phead-h) * 2)']);
    expect(bars.map((b) => b.style.getPropertyValue('--_bottom'))).toEqual(['calc(var(--hd-phead-h) * 2)', 'calc(var(--hd-phead-h) * 1)', '0px']);
    expect(host.querySelector<HTMLElement>('[data-task-manager-scroll]')!.getAttribute('style')).toContain('--hd-phead-h: 30px');
    setSectionFolded(projectFoldKey('18'), true);
    await settle();
    expect(host.querySelectorAll('.hd-group').length).toBe(3);
    expect(host.querySelector('[data-task-manager-block="18"]')).toBeNull();
    expect(host.querySelector('[data-task-manager-block="12"]')).not.toBeNull();
    setSectionFolded(projectFoldKey('18'), false);
  });

  test('each block carries its project color and where its section headers stick', async () => {
    const host = await mountBody(popout);
    const block = (list: string) => host.querySelector<HTMLElement>(`[data-task-manager-block="${list}"]`)!;
    expect(block('12').style.getPropertyValue('--hd-project')).toBe('#4e69ba');
    expect(block('18').style.getPropertyValue('--hd-project')).toBe('#7457c2');
    expect(block('21').style.getPropertyValue('--hd-project')).toBe('var(--oc-text-secondary)');
    expect(block('12').style.getPropertyValue('--hd-stick-top')).toBe('calc(var(--hd-phead-h) * 1)');
    expect(block('21').style.getPropertyValue('--hd-stick-top')).toBe('calc(var(--hd-phead-h) * 3)');
    expect(block('12').querySelector('[data-task-manager-status-head]')).not.toBeNull();
    expect(block('12').querySelector('[data-huddle-item]')).not.toBeNull();
  });

  test('a single project list: no project bar, its own color on the block, headers stick at 0', async () => {
    huddle.selected = '18';
    await refreshTaskManager();
    const host = await mountBody(popout);
    expect(host.querySelector('.hd-group')).toBeNull();
    const block = host.querySelector<HTMLElement>('[data-task-manager-block="18"]')!;
    expect(block.style.getPropertyValue('--hd-project')).toBe('#7457c2');
    expect(block.style.getPropertyValue('--hd-stick-top')).toBe('0px');
  });

  test('each status section is its own wrapper (header and list), so a header lets go where its section ends', async () => {
    const host = await mountBody(popout);
    const sections = [...host.querySelectorAll<HTMLElement>('[data-task-manager-block="12"] .hss-section')];
    expect(sections.length).toBeGreaterThan(1);
    for (const section of sections) {
      expect(section.querySelectorAll(':scope > .hss-head').length).toBe(1);
      expect(section.querySelectorAll(':scope > .hss-list').length).toBe(1);
    }
  });

  test('by group: each group is its own wrapper too', async () => {
    server.view = 'area';
    await refreshPrefs();
    const host = await mountBody(popout);
    const sections = [...host.querySelectorAll<HTMLElement>('[data-task-manager-block="12"] .hds-section')];
    expect(sections.length).toBeGreaterThan(1);
    expect(sections.some((s) => s.querySelector(':scope > .hds-head') !== null)).toBe(true);
  });
});

describe('the rules', () => {
  test('the project bar is sticky with both offsets, one fixed height and an opaque ground, above the section headers', () => {
    const bar = rule('./TaskManagerProjectHead.svelte', '.hd-group');
    expect(bar).toContain('position: sticky');
    expect(bar).toContain('top: var(--_top, 0)');
    expect(bar).toContain('bottom: var(--_bottom, 0)');
    expect(bar).toContain('height: var(--hd-phead-h)');
    expect(bar).toContain('background: var(--oc-ground-panel)');
    const z = (css: string) => Number(/z-index:\s*(\d+)/.exec(css)?.[1]);
    expect(z(bar)).toBeGreaterThan(z(rule('./TaskManagerStatusSections.svelte', '.hss-head')));
    expect(z(bar)).toBeGreaterThan(z(rule('./TaskManagerSections.svelte', '.hds-head')));
  });

  test('section and group headers stick under the project bars', () => {
    for (const [file, selector] of [['./TaskManagerStatusSections.svelte', '.hss-head'], ['./TaskManagerSections.svelte', '.hds-head']]) {
      const css = rule(file as string, selector as string);
      expect(css, selector).toContain('position: sticky');
      expect(css, selector).toContain('top: var(--hd-stick-top, 0px)');
    }
  });

  test('items are one step in, and the project bar is 3px in the project color with room beside it', () => {
    expect(rule('./TaskManagerRow.svelte', '.hdr')).toContain('padding: 4px 8px 4px 18px');
    expect(rule('./TaskManagerRow.svelte', '.tkm-state')).toContain('inset: 0 auto 1px 5px');
    const css = source('./HuddleBody.svelte');
    expect(css).toContain("[data-huddle-item], [data-task-manager-level='status'], [data-task-manager-level='area'], [data-task-manager-level='sub'], [data-task-manager-group-empty]");
    expect(css).toContain('width: 3px;\n      background: var(--hd-project');
  });
});
