/* the Task Manager */
import { registerPluginCell } from '../../opscenter/cells/registry';
import type { CplugCell } from '../sdk';

export function registerCplugCells(cplug: { cells?: readonly CplugCell[] }): string[] {
  return (cplug.cells ?? []).map((cell) => {
    registerPluginCell(cell.id, cell.component);
    return cell.id;
  });
}

export function registerShippedCells(cplugs: ReadonlyArray<{ cells?: readonly CplugCell[] }>): void {
  for (const cplug of cplugs) registerCplugCells(cplug);
}
