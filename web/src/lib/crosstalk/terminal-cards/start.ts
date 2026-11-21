import { registerTerminalOverlay } from '../../../plugins/sdk/terminal';
import { followKept } from './keep.svelte';
import { mountCardLayer } from './overlay';
import { followSettings } from './prefs.svelte';

let started = false;

export function startCrosstalkCards(): void {
  if (started) return;
  started = true;
  followSettings();
  followKept();
  registerTerminalOverlay(mountCardLayer);
}
