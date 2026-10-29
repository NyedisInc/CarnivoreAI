
<script lang="ts">
  import { t } from '../../../i18n/index.svelte';
  import type { RosterAgent } from '../../board-data.svelte';
  import ChatWidget from '../../../../cplugs/huddle/chat/ChatWidget.svelte';
  import { chatSlotId } from '../../../../cplugs/huddle/chat/chat-model';
  import { createChatStore } from '../../../../cplugs/huddle/chat/chat-store.svelte';
  import { openAgentPage } from '../../../../cplugs/huddle/agents/agent-page.svelte';

  let { agent }: { agent: RosterAgent | null } = $props();

  const agentId = $derived(agent?.id ?? null);
  const chat = $derived(agentId === null ? null : createChatStore(agentId));
  $effect(() => chat?.start());
</script>

<div class="sbch" class:sbch--none={agentId === null} data-swarm-cell="chat" data-swarm-lane-chat={agentId ?? 'none'}>
  {#if agent && agentId !== null && chat}
    <div class="sbch-head">
      <span class="sbch-name">{agent.display_name}</span>
      <button type="button" class="oc-btn oc-btn--sm sbch-open" data-swarm-chat-open={agentId} onclick={() => openAgentPage(agentId)}>{t('swarm.board.chat.open')}</button>
    </div>
    <div class="sbch-body">
      {#key agentId}
        <ChatWidget instance={chatSlotId(agentId)} framed {chat} />
      {/key}
    </div>
  {:else}
    <span class="sbch-none" data-swarm-chat-none>{t('swarm.board.chat.none')}</span>
  {/if}
</div>

<style>
  @layer components {
    .sbch {
      position: relative;
      display: flex;
      flex-direction: column;
      min-width: 0;
      min-height: 320px;
      border-radius: var(--oc-radius-sm);
      background: var(--oc-ground-page);
      box-shadow: inset 0 0 0 1px var(--oc-line-rule);
      overflow: hidden;
    }
    /* box-shadow */
    .sbch-head {
      display: flex;
      flex: none;
      align-items: center;
      gap: 8px;
      height: 34px;
      padding: 0 6px 0 10px;
      background: var(--oc-ground-titlerow);
      box-shadow: 0 1px 0 var(--oc-line-rule);
    }
    .sbch-name {
      flex: 1;
      min-width: 0;
      overflow: hidden;
      color: var(--oc-text-bright);
      font-size: var(--oc-fs-label);
      letter-spacing: 0.1em;
      text-overflow: ellipsis;
      text-transform: uppercase;
      white-space: nowrap;
    }
    .sbch-open {
      flex: none;
    }
    .sbch-body {
      position: absolute;
      inset: 34px 0 0;
      display: flex;
      flex-direction: column;
      min-height: 0;
    }
    .sbch--none {
      min-height: 0;
    }
    .sbch-none {
      padding: 16px 10px;
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-body);
    }
    @container swarm-board (max-width: 720px) {
      .sbch:not(.sbch--none) {
        min-height: 360px;
      }
    }
  }
</style>
