import { authFetch, resourcePush } from '../../sdk';
import type { FloorItem } from './floor';

export const NODE_ORDER_TOPIC = 'swarm_node_order';
const LIVENESS = '$live';

export type OrderTier = 'companies' | 'projects' | 'agents';

export const nodeOrder = $state<Record<OrderTier, string[]>>({ companies: [], projects: [], agents: [] });

let users = 0;
let off: (() => void) | null = null;
let writes = 0;

export async function refreshNodeOrder(): Promise<void> {
  const at = writes;
  try {
    const answer = await authFetch<Partial<Record<OrderTier, string[]>>>('/swarm/node-order');
    if (at !== writes) return;
    for (const tier of ['companies', 'projects', 'agents'] as const) nodeOrder[tier] = Array.isArray(answer[tier]) ? answer[tier] : [];
  } catch (error) {
    console.debug('cplug.huddle: the swarm node order could not be read', error);
  }
}

export function startNodeOrder(): () => void {
  users += 1;
  if (users === 1) {
    off = resourcePush().onChange((topics) => {
      if (topics.includes(NODE_ORDER_TOPIC) || topics.includes(LIVENESS)) void refreshNodeOrder();
    });
    void refreshNodeOrder();
  }
  let stopped = false;
  return () => {
    if (stopped) return;
    stopped = true;
    users -= 1;
    if (users === 0) { off?.(); off = null; }
  };
}

export function durableKey(item: FloorItem): boolean {
  return !item.ordinary || (item.session?.sessionUuid != null && item.key === `session:${item.session.sessionUuid}`);
}

export function nextOrder(shown: readonly string[], stored: readonly string[]): string[] {
  const seen = new Set(shown);
  return [...shown, ...stored.filter((k) => !seen.has(k))].slice(0, 500);
}

export async function saveTierOrder(tier: OrderTier, items: readonly FloorItem[], keys: readonly string[]): Promise<void> {
  const durable = new Set(items.filter(durableKey).map((i) => i.key));
  const next = nextOrder(keys.filter((k) => durable.has(k)), nodeOrder[tier]);
  writes += 1;
  nodeOrder[tier] = next;
  try {
    await authFetch('/swarm/node-order', { method: 'PUT', body: JSON.stringify({ tier, keys: next }) });
  } catch (error) {
    console.debug('cplug.huddle: the swarm node order was refused', error);
    writes += 1;
    await refreshNodeOrder();
  }
}
