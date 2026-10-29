/* waiting on the user */
import { widgetSetting } from '../item-settings/store.svelte';
import { t } from '../i18n/index.svelte';
import type { SessionScope } from '../../opscenter/widgets/session-scope';
import type { PlacementOptions } from '../../opscenter/widgets/placement-options';
import type { MenuNode } from '../drawer-tabs/add-component-menu';

export const ALERT_BADGE_MAX = 99;

export interface AlertCountSource {
  hold?(scope: SessionScope | null): () => void;
  read(scope: SessionScope | null, options?: PlacementOptions): number | null;
  menu?: { headingKey: string; nodes(): MenuNode[] };
}

const sources = new Map<string, AlertCountSource>();

export function registerAlertCount(widgetId: string, source: AlertCountSource): void {
  sources.set(widgetId, source);
}

export function alertCountSource(widgetId: string): AlertCountSource | undefined {
  return sources.get(widgetId);
}

export function alertBadgeEnabled(widgetId: string): boolean {
  return widgetSetting(widgetId, 'showBadge') !== false;
}

export function alertBadgeText(count: number | null | undefined): string | null {
  if (count == null || !Number.isFinite(count) || count <= 0) return null;
  return count > ALERT_BADGE_MAX ? t('session_rail.badge_over') : String(Math.floor(count));
}
