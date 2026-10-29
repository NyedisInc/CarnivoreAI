
<script lang="ts">
    import AgentChatFrame from '../agents/AgentChatFrame.svelte';
    import type { AgentDrawerTab } from '../agents/agent-page.svelte';
    import ChatWidget from './ChatWidget.svelte';
    import { agentIdOf } from './chat-model';

    let { instance, store, onOpenedTerminal }: { instance?: string; store?: unknown; onOpenedTerminal?: () => void } = $props();

    const agentId = $derived(agentIdOf(instance));
    let tab = $state<AgentDrawerTab>('chat');
</script>

{#if agentId === null}
    <ChatWidget {instance} {store} {onOpenedTerminal} />
{:else}
    <div class="hdw" data-chat-widget-host={agentId}>
        <AgentChatFrame id={agentId} bind:tab {store} {onOpenedTerminal} />
    </div>
{/if}

<style>
  @layer components {
    .hdw {
      display: flex;
      flex-direction: column;
      height: 100%;
      min-height: 0;
      min-width: 0;
    }
  }
</style>
