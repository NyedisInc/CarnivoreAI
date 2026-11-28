import { isPageTab } from './page-tabs';
import { currentWidgetId } from './retired-widget-ids';

export const WIDGET_TAB_PREFIX = 'widget:';

const WIDGET_ID = /^[a-z0-9][a-z0-9._-]{0,63}$/;

const WIDGET_TARGET = /^[a-z0-9][a-z0-9-]{0,31}$/;

const TARGET_JOIN = '@';

export function widgetTabId(widgetId: string, target?: string | null): string {
  return WIDGET_TAB_PREFIX + widgetId + (target ? TARGET_JOIN + target : '');
}

function splitWidgetTab(tab: string): { id: string; target: string | null } | null {
  if (typeof tab !== 'string' || !tab.startsWith(WIDGET_TAB_PREFIX)) return null;
  const rest = tab.slice(WIDGET_TAB_PREFIX.length);
  const at = rest.indexOf(TARGET_JOIN);
  const id = at < 0 ? rest : rest.slice(0, at);
  const target = at < 0 ? null : rest.slice(at + 1);
  if (!WIDGET_ID.test(id) || (target !== null && !WIDGET_TARGET.test(target))) return null;
  return { id, target };
}

export function widgetTargetOfTab(tab: string): string | null {
  return splitWidgetTab(tab)?.target ?? null;
}

export function widgetIdOfTab(tab: string): string | null {
  const id = splitWidgetTab(tab)?.id;
  return id ? currentWidgetId(id) : null;
}

export function isWidgetTab(tab: string): boolean {
  return widgetIdOfTab(tab) !== null;
}

export function isNonSessionTab(tab: string): boolean {
  return isPageTab(tab) || isWidgetTab(tab);
}
