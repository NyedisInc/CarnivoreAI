import { lookOf, type NodeLooks } from './node-look';
import { createSwarmLive } from './swarm-live.svelte';

export function createNodeLooks(): NodeLooks {
  const live = createSwarmLive(true);
  return {
    of: (ref) => lookOf(live.floor, live.colors, ref, live.now),
    get pack() { return live.pack; },
  };
}
