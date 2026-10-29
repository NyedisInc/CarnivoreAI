
<script lang="ts">
  import { swarmFace } from '../../cplugs/sdk/swarm-face.svelte';
  import { statusTitle } from '../status-dot';
  import type { AgentMarkFacts } from '../sessions/agent-marks';
  import { memberState, type Membership } from './member-face';

  let { facts, member }: { facts: AgentMarkFacts; member: Membership } = $props();

  const face = $derived(memberState(facts));
  const Face = $derived(swarmFace.component);
  const title = $derived(statusTitle(facts.status, facts.statusSource, facts.activityHint, facts.unread, facts.parkedSummary ?? null, facts.hostOffline ?? null, facts.usageLimit ?? null));
</script>

<span class="swarm-row-face" data-swarm-member={member.agentId} data-unread={face.unread ? '1' : undefined} role="img" aria-label={title} title={title}>{#if Face}<Face state={face.state} size={13} agentId={member.agentId} seed={member.seed} rank={member.rank} />{/if}</span>

<style>
  @layer components {
    .swarm-row-face {
      position: relative;
      display: inline-flex;
      flex: none;
      align-items: center;
      justify-content: center;
      width: var(--led-size, 9px);
      height: var(--led-size, 9px);
      overflow: visible;
    }
    .swarm-row-face > :global(.pk-sq) {
      position: absolute;
      left: 50%;
      top: 50%;
      translate: -50% -50%;
    }
    .swarm-row-face[data-unread]::after {
      content: '';
      position: absolute;
      inset: -4px;
      border-radius: var(--radius-full);
      box-shadow: 0 0 0 1px var(--oc-green);
      pointer-events: none;
    }
  }
</style>
