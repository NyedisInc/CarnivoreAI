/* the Task Manager */
import { afterEach, expect, test } from 'vitest';

import { BUILTIN_CPLUGS } from '../builtin';
import { POPOUT_CPLUGS } from '../popout';
import { taskManagerCells } from '../taskmanager/cells';
import { PLUGIN_CELL_IDS, entryFor } from '../../opscenter/cells/registry';
import { cplugEnablement } from './enablement.svelte';
import { bootPluginCells } from './cell-boot';

afterEach(() => {
  cplugEnablement.enabled = {};
});

test('every plugin cell id is drawn by exactly one plugin, in the main ship list and in the pop-out ship list', () => {
  for (const [name, list] of [['BUILTIN_CPLUGS', BUILTIN_CPLUGS], ['POPOUT_CPLUGS', POPOUT_CPLUGS]] as const) {
    for (const id of PLUGIN_CELL_IDS) {
      const owners = list.filter((cplug) => (cplug.cells ?? []).some((cell) => cell.id === id)).map((cplug) => cplug.id);
      expect(owners, `${name}: ${id}`).toEqual(['taskmanager']);
    }
  }
});

test('the cell boot registers Mark II and its all projects view with the Task Manager switched off', () => {
  for (const id of PLUGIN_CELL_IDS) expect(entryFor(id)).toBeUndefined();
  cplugEnablement.enabled = { taskmanager: false };
  bootPluginCells();
  for (const { id, component } of taskManagerCells) expect(entryFor(id)?.component).toBe(component);
  expect(taskManagerCells.map((cell) => cell.id).sort()).toEqual([...PLUGIN_CELL_IDS].sort());
});
