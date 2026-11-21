import { openTabFlyout } from '../sdk';
import type { DynamicTabDef } from '../sdk';
import { listenForMenuRequests } from './menu-request';
import LabMenu from './LabMenu.svelte';
import LabViewer from './LabViewer.svelte';

export const devwidgetlabTab: DynamicTabDef = {
  id: 'devwidgetlab',
  labelKey: 'cplug.devwidgetlab.tab',
  icon: 'grid',
  order: 41,
  persist: false,
  popout: true,
  onAppear: () => listenForMenuRequests(() => openTabFlyout('devwidgetlab')),
  focusOnAppear: false,
  widgetArea: 'closed',
  mainView: LabViewer,
  body: { component: LabMenu, titleKey: 'cplug.devwidgetlab.menu.title' },
};
