import type { DynamicTabDef } from '../sdk';
import LabViewer from './LabViewer.svelte';

export const devwidgetlabViewerTab: DynamicTabDef = {
  id: 'devwidgetlab',
  labelKey: 'cplug.devwidgetlab.tab',
  icon: 'grid',
  order: 41,
  persist: false,
  popout: true,
  focusOnAppear: false,
  widgetArea: 'closed',
  body: { component: LabViewer, titleKey: 'cplug.devwidgetlab.page.title' },
};
