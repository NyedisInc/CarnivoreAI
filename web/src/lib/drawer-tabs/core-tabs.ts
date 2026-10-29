import type { DynamicTabDef } from '../dynamic-tabs/types';
import DrawerMenu from './DrawerMenu.svelte';
import DrawerQuestions from './DrawerQuestions.svelte';
import { approvals } from '../approvals/approvals.svelte';
import { badgeCount } from '../approvals/approvals-model';
import { DRAWER_LIST_ID, DRAWER_SEARCH_ID, DRAWER_STATS_ID, QUESTIONS_TAB } from './drawer-tabs';

function waiting(): number | null {
  return badgeCount(approvals.items.length);
}

export const menuTab: DynamicTabDef = {
  id: 'menu',
  labelKey: 'drawer.tabs.menu',
  icon: 'home',
  order: 10,
  persist: true,
  widgetArea: 'glance',
  body: { component: DrawerMenu },
};

export const agentsTab: DynamicTabDef = {
  id: 'agents',
  labelKey: 'drawer.tabs.agents',
  icon: 'bot',
  order: 20,
  persist: true,
  widgetArea: 'full',
  body: { containers: [DRAWER_LIST_ID, DRAWER_SEARCH_ID, DRAWER_STATS_ID] },
};

export const questionsTab: DynamicTabDef = {
  id: QUESTIONS_TAB,
  labelKey: 'drawer.tabs.questions',
  icon: 'question',
  order: 30,
  persist: false,
  present: () => waiting() !== null,
  badge: waiting,
  tone: 'question',
  widgetArea: 'glance',
  body: { component: DrawerQuestions },
};
