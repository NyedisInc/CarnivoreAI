/* the Task Manager the widgets page */
import { POPOUT_CPLUGS } from '../popout';
import { registerShippedCells } from './cells';

/* the Task Manager */
export function bootPluginCells(): void {
  registerShippedCells(POPOUT_CPLUGS);
}
