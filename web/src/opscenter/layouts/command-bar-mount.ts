import { mountPanel } from '../../lib/mount';
import LayoutCommandBar from './LayoutCommandBar.svelte';

export const COMMAND_BAR_CONTAINER_ID = 'layout-command-bar';

let mounted = false;

export function mountLayoutCommandBar(): void {
  if (mounted) return;
  mounted = mountPanel(COMMAND_BAR_CONTAINER_ID, LayoutCommandBar) !== null;
}
