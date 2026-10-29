import type { DynamicTabDef } from '../sdk';
import { swarmSwitch } from '../../lib/swarm-switch/control.svelte';
import { huddle } from './huddle.svelte';
import { taskManagerPrefs } from './task-manager-prefs.svelte';
import { LIST_PARAM } from './huddle-model';
import { TASK_MANAGER_TAB } from './huddle-tab-id';
import HuddleBody from './HuddleBody.svelte';
import SwarmTitleActions from './swarm/SwarmTitleActions.svelte';

export function swarmIsOn(): boolean {
  return swarmSwitch.data?.enabled !== false;
}

export const taskManagerTab: DynamicTabDef = {
  id: TASK_MANAGER_TAB,
  labelKey: 'cplug.huddle.tab',
  icon: 'swarm',
  order: 35,
  persist: false,
  present: () => taskManagerPrefs.showTab && swarmIsOn(), //  hidden 
  focusOnAppear: false,
  open: () => taskManagerPrefs.showTab && swarmIsOn(),
  widgetArea: 'glance',
  popout: true,
  popoutMulti: true,
  popoutParams: () => ({ [LIST_PARAM]: huddle.selected }),
  body: { component: HuddleBody, titleKey: 'cplug.huddle.title', titleActions: SwarmTitleActions },
};
