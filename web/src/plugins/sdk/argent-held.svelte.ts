import { argentCost } from '../../lib/argent-cost/cost-store.svelte';
import { heldRowIds } from '../../lib/argent-cost/cost-view';

export function argentHeldRows(): ReadonlySet<number> {
  return heldRowIds(argentCost().data);
}
