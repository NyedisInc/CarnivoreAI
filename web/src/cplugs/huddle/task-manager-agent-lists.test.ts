/** @vitest-environment jsdom */
import { describe, expect, test } from 'vitest';
import { mount, unmount } from 'svelte';
import { isAgentList, listFallback, listFromSearch, moveTargets } from './huddle-model';
import { startSessionFor } from './task-manager-send-start';
import TaskManagerTargetPick from './TaskManagerTargetPick.svelte';
import enCatalog from '../../../../client/js/i18n/catalog.en.js';

describe('agent lists', () => {
  test('listFromSearch keeps agent keys and still refuses junk', () => {
    expect(listFromSearch('?list=agent:5')).toBe('agent:5');
    expect(listFromSearch('?list=agent:0')).toBeNull();
    expect(listFromSearch('?list=agent:x')).toBeNull();
    expect(listFromSearch('?list=18')).toBe('18');
  });

  test('a null project id falls back to the agent id, never a project label', () => {
    expect(isAgentList('agent:5')).toBe(true);
    expect(isAgentList('5')).toBe(false);
    expect(listFallback('agent:5')).toEqual({ key: 'cplug.huddle.list.agent', id: '5' });
    expect(listFallback('7')).toEqual({ key: 'cplug.huddle.list.project', id: '7' });
    expect((enCatalog as Record<string, string>)['cplug.huddle.list.agent']).toBe('agent {id}');
  });

  test('moving never offers an agent list as a target (#2567 u124-04)', () => {
    const rows = [{ key: 'all' }, { key: '7' }, { key: 'agent:5' }];
    expect(moveTargets(rows, '7').map((r) => r.key)).toEqual(['all']);
  });

  test('no start new for an agent list, and starting one is refused', async () => {
    const draw = (list: string): string => {
      const host = document.createElement('div');
      const app = mount(TaskManagerTargetPick, { target: host, props: { list, sessions: [], value: '', label: 'x', onPick: () => {} } });
      const html = host.innerHTML;
      void unmount(app);
      return html;
    };
    expect(draw('7')).toContain('data-task-manager-target-new');
    expect(draw('agent:5')).not.toContain('data-task-manager-target-new');
    expect(await startSessionFor('agent:5')).toEqual({ session: null, failure: 'no_project' });
  });
});
