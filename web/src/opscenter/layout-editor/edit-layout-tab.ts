import type { DynamicTabDef } from '../../lib/dynamic-tabs/types';
import { enterLayoutEditor, finishLayoutEditor, layoutEditor } from './editor.svelte';
import EditLayoutBody from './EditLayoutBody.svelte';
import { showDrawerForPage } from '../../lib/drawer/show-drawer';

export const EDIT_LAYOUT_TAB = 'edit-layout';

export const editLayoutTab: DynamicTabDef = {
  id: EDIT_LAYOUT_TAB,
  labelKey: 'drawer.tabs.edit_layout',
  icon: 'layout',
  order: 40,
  persist: false,
  present: () => layoutEditor.active,
  focusOnAppear: true,
  onAppear: showDrawerForPage,
  open: () => enterLayoutEditor(),
  close: () => {
    void finishLayoutEditor();
  },
  widgetArea: 'full',
  body: { component: EditLayoutBody },
};
