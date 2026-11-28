import { lazyComponent, openTabFlyout } from '../sdk';
import type { DynamicTabDef } from '../sdk';
import { listenForMenuRequests } from './menu-request';

const LabMenu = lazyComponent(() => import('./LabMenu.svelte'));
const LabViewer = lazyComponent(() => import('./LabViewer.svelte'));

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
