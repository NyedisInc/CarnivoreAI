
<script lang="ts">
  import AgentFace from '../../AgentFace.svelte';
  import type { BoardData, RosterAgent } from '../../board-data.svelte';

  interface Props {
    agent: RosterAgent;
    data: BoardData;
  }
  let { agent, data }: Props = $props();
  const body = $derived((data.looks?.of({ agentId: agent.id })?.color ?? data.colors.of(agent)).body);
</script>

<span class="sbt-node" data-swarm-tl-node={agent.id}>
  <AgentFace {agent} working colors={data.colors} looks={data.looks} size={18} />
  <span class="sbt-node-stem" style:background={body}></span>
</span>

<style>
  @layer components {
    .sbt-node {
      display: inline-flex;
      flex-direction: column;
      align-items: center;
    }
    .sbt-node-stem {
      width: 1px;
      height: 8px;
    }
  }
</style>
