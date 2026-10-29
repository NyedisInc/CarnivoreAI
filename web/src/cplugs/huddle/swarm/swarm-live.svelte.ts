import { authFetch, floorSource, openFloorSession, sessionRow } from '../../sdk';
import { startSwarmRoster, swarmRoster, refreshRoster } from '../agents/agent-roster.svelte';
import { openAgentPage } from '../agents/agent-page.svelte';
import { openAgentTerminal } from '../agents/agent-terminal';
import { swarmInactive } from '../huddle-swarm-inactive.svelte';
import { DEFAULT_PACK, type CharacterPack } from './characters';
import { colorBook, type ColorBook } from './agent-colors.svelte';
import { buildFloor, orderFloor, type Floor, type FloorTarget } from './floor';
import { nodeOrder, startNodeOrder } from './node-order.svelte';
import { ACTIVITY_MS, type PanelAgent } from './panel-state';
import { activePack, loadSwarmSettings, swarmSettings } from './swarm-settings.svelte';

export interface SwarmLive {
  readonly floor: Floor;
  readonly agents: readonly PanelAgent[];
  readonly now: number;
  readonly pack: CharacterPack;
  readonly threadsReady: boolean | null;
  readonly colors: ColorBook;
}

export function createSwarmLive(all = false): SwarmLive {
  let now = $state(Date.now());
  let pack = $state<CharacterPack>(DEFAULT_PACK);

  $effect(() => startSwarmRoster());
  $effect(() => startNodeOrder());
  $effect(() => {
    if (!swarmSettings.loaded) void loadSwarmSettings();
  });

  $effect(() => {
    const t0 = Date.now();
    now = t0;
    const ends = swarmRoster.agents
      .map((a) => (a.activity && typeof a.activity_at === 'number' ? a.activity_at * 1000 + ACTIVITY_MS : 0))
      .filter((end) => end > t0);
    if (ends.length === 0) return;
    const timer = setTimeout(() => (now = Date.now()), Math.min(...ends) - t0 + 50);
    return () => clearTimeout(timer);
  });

  $effect(() => {
    void swarmSettings.character_pack;
    pack = activePack();
    const watch = new MutationObserver(() => (pack = activePack()));
    watch.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    return () => watch.disconnect();
  });

  const source = $derived(floorSource());
  const floor = $derived.by(() => orderFloor(
    buildFloor({ agents: swarmRoster.agents, ...source, rowOf: (id) => sessionRow(id ?? null), showInactive: all || swarmInactive.shown }), nodeOrder));
  const colors = $derived(colorBook(swarmRoster.agents, source));

  return {
    get floor() { return floor; },
    get agents() { return swarmRoster.agents; },
    get now() { return now; },
    get pack() { return pack; },
    get threadsReady() { return swarmRoster.threadsReady; },
    get colors() { return colors; },
  };
}

export function openFloorTarget(target: FloorTarget, terminal = false): void {
  if (target.kind === 'session') void openFloorSession(target.session);
  else if (target.kind === 'agent') {
    if (terminal) void openAgentTerminal(target.agentId);
    else openAgentPage(target.agentId);
  }
}

export async function turnOnSeat(target: Extract<FloorTarget, { kind: 'turn_on' }>): Promise<void> {
  await authFetch(`/swarm/${target.scope === 'company' ? 'companies' : 'projects'}/${target.id}/agent`, { method: 'POST' });
  await refreshRoster();
}
