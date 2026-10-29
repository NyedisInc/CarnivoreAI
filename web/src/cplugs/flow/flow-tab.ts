import type { DynamicTabDef } from '../sdk';
import FlowBody from './FlowBody.svelte';
import { flowPrefs } from './flow-prefs.svelte';

export const flowTab: DynamicTabDef = {
  id: 'flow',
  labelKey: 'cplug.flow.tab',
  icon: 'activity',
  order: 38,
  persist: false,
  popout: true,
  present: () => flowPrefs.showTab,
  focusOnAppear: false,
  widgetArea: 'closed',
  body: { component: FlowBody, titleKey: 'cplug.flow.chat.title' },
};
