import { authFetch } from '../../opscenter/api/auth.svelte';
import { resource, type Resource } from '../../opscenter/api/poll.svelte';
import type { ArgentCostSnapshot } from './cost-view';

let held: Resource<ArgentCostSnapshot> | null = null;

export function argentCost(): Resource<ArgentCostSnapshot> {
  held ??= resource<ArgentCostSnapshot>(
    () => authFetch<ArgentCostSnapshot>('/argent/cost'),
    { intervalMs: 60_000, name: 'argent-cost', demo: () => ({ enabled: false, state: 'off' }), topics: ['argent_cost'] },
  );
  return held;
}
