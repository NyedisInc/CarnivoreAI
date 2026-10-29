/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { mount, unmount } from 'svelte';

import enCatalog from '../../../../client/js/i18n/catalog.en.js';
import { t } from '../../lib/i18n/index.svelte';
import { markRankOf } from '../../cplugs/huddle/swarm/node-look';
import type { FloorItem } from '../../cplugs/huddle/swarm/floor';
import TaskMark from './TaskMark.svelte';

let mounted: Record<string, unknown> | null = null;

afterEach(() => {
  if (mounted) unmount(mounted);
  mounted = null;
  document.body.innerHTML = '';
});

function show(rank: string | null): HTMLElement | null {
  mounted = mount(TaskMark, { target: document.body, props: { rank } });
  return document.body.querySelector<HTMLElement>('[data-task-mark]');
}

describe('TaskMark', () => {
  test('a task agent shows the hourglass with its label and tooltip', () => {
    const mark = show('task');
    expect(mark).not.toBeNull();
    expect(mark!.querySelector('svg[data-icon="hourglass"]')).not.toBeNull();
    expect(mark!.getAttribute('role')).toBe('img');
    expect(mark!.getAttribute('aria-label')).toBe(t('swarm.agent.task_mark'));
    expect(mark!.getAttribute('title')).toBe(t('swarm.agent.task_mark'));
    expect((enCatalog as Record<string, string>)['swarm.agent.task_mark']).toBe('temporary task agent');
  });

  test.each(['feature', 'project', 'company', 'alpha', null])('rank %s shows no mark', (rank) => {
    expect(show(rank)).toBeNull();
  });

  test('the floor marks a Swarm task agent, never an ordinary session stand-in or a seat', () => {
    const agent = { id: 1, display_name: 'fixing node colors', rank: 'task', state: 'awake', thread_key: 't' };
    const item = { ordinary: false, vacant: false, rank: 'task', agent } as unknown as FloorItem;
    expect(markRankOf(item)).toBe('task');
    expect(markRankOf({ ...item, agent: { ...agent, rank: 'feature' } } as unknown as FloorItem)).toBe('feature');
    expect(markRankOf({ ...item, ordinary: true } as unknown as FloorItem)).toBeNull();
    expect(markRankOf({ ...item, agent: null, vacant: true } as unknown as FloorItem)).toBeNull();
  });
});
