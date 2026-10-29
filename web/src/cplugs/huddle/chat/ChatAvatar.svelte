<script lang="ts">
  import { ownerIdentity, t } from '../../sdk';
  import { Icon, Identicon } from '../../sdk/ui';
  import { Character } from '../swarm/characters';
  import type { NodeLooks } from '../swarm/node-look';
  import { avatarColorOf, avatarSeedOf, initialsOf, rosterAgent } from './chat-avatar';
  import type { BurstParty } from './chat-model';

  let { party, name, looks = null }: { party: BurstParty; name: string; looks?: NodeLooks | null } = $props();

  const node = $derived(party.owner ? null : (looks?.of({ agentId: party.agentId, sessionUuid: party.sessionUuid }) ?? null));
  const agent = $derived(node ? null : rosterAgent(party.agentId));
  const label = $derived(party.dir ? t(`cplug.huddle.chat.burst.${party.dir}`) : '');
  const owner = $derived(party.owner ? ownerIdentity() : null);
  const member = $derived(owner?.kind === 'member' && owner.name ? owner.name : '');
</script>

<span class="hdc-av" data-chat-dir={party.dir ?? 'none'}>
  {#if party.dir}
    <span class="hdc-av-dir hdc-av-dir--{party.dir}" title={label} aria-label={label} role="img"><Icon name={party.dir === 'to' ? 'arrow-out' : 'arrow-in'} size={12} /></span>
  {/if}
  {#if party.owner}
    <span class="hdc-av-you" class:hdc-av-you--icon={!!member} data-chat-owner-av={member ? 'icon' : 'initials'} aria-hidden="true">
      {#if member}<Identicon handle={member} size={26} />{:else}{initialsOf(party.path[party.path.length - 1]?.name ?? '')}{/if}
    </span>
  {:else if node}
    <Character state={node.state} size={28} seed={node.seed} color={node.color} tell={node.tell} pack={looks?.pack} rank={node.agent.rank} shape={node.shape} background={node.background} label={name} />
  {:else}
    <Character state="unknown" size={28} seed={avatarSeedOf(agent, name)} color={avatarColorOf(agent)} label={name} />
  {/if}
</span>

<style>
  @layer components {
    .hdc-av {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      flex: none;
    }

    .hdc-av-dir {
      display: inline-flex;
      flex: none;
    }

    .hdc-av-dir--from { color: var(--oc-cyan); }
    .hdc-av-dir--to { color: var(--oc-text-dim); }

    .hdc-av-you {
      display: grid;
      place-items: center;
      width: 28px;
      height: 28px;
      flex: none;
      border-radius: var(--oc-control-radius, 2px);
      box-shadow: inset 0 0 0 1px var(--oc-green-dim);
      color: var(--oc-green);
      font-size: 9px;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }

    .hdc-av-you--icon { overflow: hidden; }
  }
</style>
