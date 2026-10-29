
export const AUTOMATIONS_TABS = ['automations', 'sessions', 'advanced'] as const;

export type AutomationsTab = (typeof AUTOMATIONS_TABS)[number];

export const DEFAULT_TAB: AutomationsTab = 'automations';

export const AUTOMATIONS_TAB_KEY = 'automations';

export const ADVANCED_TABS = ['automations', 'sessions'] as const;

export type AdvancedTab = (typeof ADVANCED_TABS)[number];

export const DEFAULT_ADVANCED_TAB: AdvancedTab = 'automations';

export const ADVANCED_TAB_KEY = 'automations-advanced';

export function effectiveTab(wanted: string): AutomationsTab {
  return (AUTOMATIONS_TABS as readonly string[]).includes(wanted) ? (wanted as AutomationsTab) : DEFAULT_TAB;
}

export function effectiveAdvancedTab(wanted: string): AdvancedTab {
  return (ADVANCED_TABS as readonly string[]).includes(wanted) ? (wanted as AdvancedTab) : DEFAULT_ADVANCED_TAB;
}
