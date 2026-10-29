import { isPageTab } from './page-tabs';

export const WIDGET_TAB_PREFIX = 'widget:';

const WIDGET_ID = /^[a-z0-9][a-z0-9._-]{0,63}$/;

export function widgetTabId(widgetId: string): string {
  return WIDGET_TAB_PREFIX + widgetId;
}

export function widgetIdOfTab(tab: string): string | null {
  if (typeof tab !== 'string' || !tab.startsWith(WIDGET_TAB_PREFIX)) return null;
  const id = tab.slice(WIDGET_TAB_PREFIX.length);
  return WIDGET_ID.test(id) ? id : null;
}

export function isWidgetTab(tab: string): boolean {
  return widgetIdOfTab(tab) !== null;
}

export function isNonSessionTab(tab: string): boolean {
  return isPageTab(tab) || isWidgetTab(tab);
}
