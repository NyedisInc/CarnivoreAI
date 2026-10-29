
<script lang="ts">
  import { Character } from '../../cplugs/huddle/swarm/characters';
  import { activePack } from '../../cplugs/huddle/swarm/swarm-settings.svelte';
  import type { ColorBook } from '../../cplugs/huddle/swarm/agent-colors.svelte';
  import type { NodeLooks } from '../../cplugs/huddle/swarm/node-look';
  import type { RosterAgent } from './board-data.svelte';

  interface Props {
    agent: RosterAgent;
    working: boolean;
    colors: ColorBook;
    looks?: NodeLooks | null;
    size?: number;
  }
  let { agent, working, colors, looks = null, size = 16 }: Props = $props();
  const node = $derived(looks?.of({ agentId: agent.id }) ?? null);
  const pack = $derived(looks?.pack ?? activePack());
  const state = $derived(node?.state ?? (agent.state === 'asleep' ? 'asleep' : 'unknown'));
</script>

<span class="sbf" class:sbf--idle={!working} title={agent.display_name} data-swarm-board-face={agent.id} data-working={working ? 'true' : 'false'}>
  <Character {state} {size} seed={agent.character_seed ?? agent.id} color={node ? node.color : colors.of(agent)} {pack} still rank={agent.rank} shape={node?.shape} background={node?.background} label={agent.display_name} />
</span>

<style>
  @layer components {
    .sbf {
      display: inline-flex;
      flex: none;
    }
    .sbf--idle {
      opacity: 0.45;
    }
  }
</style>
