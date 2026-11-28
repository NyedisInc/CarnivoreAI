import { lazyComponent, type DynamicTabDef } from '../sdk';

const BoardScreen = lazyComponent(() => import('./BoardScreen.svelte'));

export const reviewboardTab: DynamicTabDef = {
  id: 'reviewboard',
  labelKey: 'cplug.reviewboard.tab',
  icon: 'docs',
  order: 39,
  persist: false,
  popout: true,
  present: () => false,
  focusOnAppear: false,
  widgetArea: 'closed',
  body: { component: BoardScreen, titleKey: 'cplug.reviewboard.page.title' },
};
