<script lang="ts">
  import { openPluginsPage } from '../../sdk';
  import { agentPage } from '../agents/agent-page.svelte';
  import { swarmInactive, setSwarmInactive } from '../huddle-swarm-inactive.svelte';
  import SwarmPanel from './SwarmPanel.svelte';
  import { scopeFloor } from './floor';
  import { createSwarmLive, openFloorTarget, turnOnSeat } from './swarm-live.svelte';
  import { effectiveDensity } from './swarm-settings.svelte';
  import { saveTierOrder } from './node-order.svelte';

  const live = createSwarmLive();
  const floor = $derived(scopeFloor(live.floor, live.agents, agentPage.id));
</script>

<SwarmPanel {floor} agents={live.agents} colors={live.colors} density={effectiveDensity()} now={live.now} pack={live.pack} onOpen={openFloorTarget} onTurnOn={turnOnSeat}
           showInactive={swarmInactive.shown} onToggleInactive={() => setSwarmInactive(!swarmInactive.shown)}
           threadsReady={live.threadsReady} onOpenPlugins={() => void openPluginsPage()}
           onReorder={(tier, keys) => void saveTierOrder(tier, floor[tier], keys)} />
