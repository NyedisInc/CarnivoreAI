import { openFlyout } from '../../lib/sidebar-widgets/flyout.svelte';
import { tabFlyoutId } from '../../lib/sidebar-widgets/tab-flyouts';

export function openTabFlyout(tab: string): boolean {
  return openFlyout(tabFlyoutId(tab));
}
