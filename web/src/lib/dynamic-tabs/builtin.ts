import { registerTab, tabRegistry } from './registry';
import { agentsTab, menuTab, questionsTab } from '../drawer-tabs/core-tabs';
import { editLayoutTab } from '../../opscenter/layout-editor/edit-layout-tab';
import { cplugTabs } from '../../cplugs/host/readers';
import type { DynamicTabDef } from './types';

export const BUILTIN_TABS: readonly DynamicTabDef[] = [menuTab, agentsTab, questionsTab, ...cplugTabs(), editLayoutTab];

for (const def of BUILTIN_TABS) if (!tabRegistry.get(def.id)) registerTab(def);
