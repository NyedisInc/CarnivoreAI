<script lang="ts">
  import { ownerIdentity } from '../../sdk';
  import { Identicon } from '../../sdk/ui';
  import { Character, type CharacterState } from '../swarm/characters';
  import type { NodeLooks } from '../swarm/node-look';
  import { avatarColorOf, avatarSeedOf, initialsOf, rosterAgent } from './chat-avatar';
  import { fullPathOf, lineageTip, openAuthorTerminal, pathTip } from './agent-open';
  import type { BurstParty } from './chat-model';

  let { party, name, looks = null, pose, size = 28, link = false }: { party: BurstParty; name: string; looks?: NodeLooks | null; pose?: CharacterState; size?: number; link?: boolean } = $props();

  const node = $derived(party.owner ? null : (looks?.of({ agentId: party.agentId, sessionUuid: party.sessionUuid }) ?? null));
  const agent = $derived(node ? null : rosterAgent(party.agentId));
  const owner = $derived(party.owner ? ownerIdentity() : null);
  const member = $derived(owner?.kind === 'member' && owner.name ? owner.name : '');
  const linked = $derived(link && !party.owner && (party.agentId !== null || !!party.sessionUuid));
  const tip = $derived(linked ? pathTip(fullPathOf(party.path, party.agentId)) : '');
</script>

{#if linked}
  <button type="button" class="hdc-av hdc-av--link" data-base-exempt="the agent node square is the drawn face of this control; base Button draws a labelled box" data-chat-dir={party.dir ?? 'none'} data-chat-node={party.agentId ?? party.sessionUuid}
          aria-label={name} use:lineageTip={tip} onclick={() => openAuthorTerminal(party.agentId, party.sessionUuid)}>{@render square()}</button>
{:else}
  <span class="hdc-av" data-chat-dir={party.dir ?? 'none'}>{@render square()}</span>
{/if}

{#snippet square()}
  {#if party.owner}
    <span class="hdc-av-you" class:hdc-av-you--icon={!!member} data-chat-owner-av={member ? 'icon' : 'initials'} aria-hidden="true">
      {#if member}<Identicon handle={member} size={26} />{:else}{initialsOf(party.path[party.path.length - 1]?.name ?? '')}{/if}
    </span>
  {:else if node}
    <Character state={pose ?? node.state} {size} seed={node.seed} color={node.color} tell={node.tell} pack={looks?.pack} rank={node.agent.rank} shape={node.shape} background={node.background} label={name} />
  {:else}
    <Character state={pose ?? 'idle'} {size} seed={avatarSeedOf(agent, name)} color={avatarColorOf(agent)} label={name} />
  {/if}
{/snippet}

<style>
  @layer components {
    .hdc-av {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      flex: none;
    }

    .hdc-av--link {
      padding: 0;
      border: 1px solid transparent;
      border-radius: var(--oc-control-radius, 2px);
      background: none;
      cursor: pointer;
    }

    .hdc-av :global(.pk-gw) { display: none; }
    .hdc-av :global(.pk-bd) { filter: none; }
    .hdc-av :global(.ident) { border: 0; }

    .hdc-av-you {
      display: grid;
      place-items: center;
      width: 28px;
      height: 28px;
      flex: none;
      border-radius: var(--oc-control-radius, 2px);
      color: var(--oc-green);
      font-size: 9px;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }

    .hdc-av-you--icon { overflow: hidden; }
  }
</style>
