
<script lang="ts">
    import type { Snippet } from 'svelte';
    import { t as appT } from '../../sdk';
    import type { Translate } from '../../sdk';
    import ChatBar from '../chat/ChatBar.svelte';
    import ChatWidget from '../chat/ChatWidget.svelte';
    import { chatSlotId, waitingCount, type ChatMenuExtra } from '../chat/chat-model';
    import { createChatStore } from '../chat/chat-store.svelte';
    import HuddleBody from '../HuddleBody.svelte';
    import type { AgentDrawerTab } from './agent-page.svelte';

    interface Props {
        id: number;
        tab: AgentDrawerTab;
        t?: Translate;
        store?: unknown;
        onOpenedTerminal?: () => void;
        onBarDown?: (event: PointerEvent) => void;
        menu?: ChatMenuExtra[];
        actions?: Snippet;
    }

    let { id, tab = $bindable(), t = appT, store, onOpenedTerminal, onBarDown, menu = [], actions }: Props = $props();

    const tabsList: { id: AgentDrawerTab; label: string }[] = $derived([
        { id: 'chat', label: t('cplug.huddle.swarm.drawer.tab_chat') },
        { id: 'tasks', label: t('cplug.huddle.swarm.drawer.tab_tasks') },
    ]);

    const chat = $derived(createChatStore(id));
    $effect(() => chat.start());
    let waitingOnly = $state(false);
    let notice = $state('');
    const waiting = $derived(waitingCount(chat.state.entries));
</script>

<div class="had-topgap" aria-hidden="true"></div>
<div class="had-barwrap" data-agent-frame-bar>
    <ChatBar agentId={id} agent={chat.state.agent} {chat} bind:waitingOnly {waiting} {store} {onOpenedTerminal} {onBarDown}
             extra={menu} framed onNotice={(text) => (notice = text)} trail={actions}>
        {#snippet tabs()}
            <div class="had-tabs" role="tablist">
                {#each tabsList as entry (entry.id)}
                    <div class="had-tabwrap" class:had-tabwrap--active={tab === entry.id}>
                        <button type="button" class="had-tab" role="tab" aria-selected={tab === entry.id} data-agent-drawer-tab={entry.id}
                                onclick={() => (tab = entry.id)}>{entry.label}</button>
                    </div>
                {/each}
            </div>
        {/snippet}
    </ChatBar>
</div>
<div class="had-body">
    {#key id}
        {#if tab === 'chat'}
            <ChatWidget instance={chatSlotId(id)} {store} {onOpenedTerminal} framed {chat} bind:waitingOnly bind:notice />
        {:else}
            <div class="had-tasks" data-agent-drawer-tasks><HuddleBody agent={id} /></div>
        {/if}
    {/key}
</div>

<style>
  @layer components {
    .had-topgap {
      flex: none;
      height: 5px;
      background: var(--oc-ground-tab-inactive);
    }

    .had-barwrap { flex: none; min-width: 0; }

    .had-tabs {
      display: flex;
      align-self: stretch;
      align-items: stretch;
      gap: 1px;
      flex: none;
      min-width: 0;
    }

    .had-tabwrap {
      display: flex;
      align-items: stretch;
      background: var(--oc-ground-tab-inactive);
      border-top: 2px solid transparent;
      border-bottom: 1px solid var(--oc-line-rule);
    }

    .had-tabwrap:hover { background: var(--oc-ground-tab-inactive-hover); }

    .had-tabwrap--active,
    .had-tabwrap--active:hover {
      background: var(--oc-ground-titlerow);
      border-top-color: var(--oc-orange);
      border-bottom-color: transparent;
    }

    .had-tab {
      display: inline-flex;
      align-items: center;
      padding: 0 10px;
      background: none;
      border: 0;
      color: var(--oc-text-dim);
      font: inherit;
      font-size: var(--oc-fs-label);
      cursor: pointer;
    }

    .had-tabwrap:hover .had-tab { color: var(--oc-text-primary); }
    .had-tabwrap--active .had-tab,
    .had-tabwrap--active:hover .had-tab { color: var(--oc-orange); }

    .had-body {
      flex: 1;
      display: flex;
      flex-direction: column;
      min-height: 0;
      min-width: 0;
    }

    .had-body > :global(*),
    .had-tasks {
      flex: 1;
      min-height: 0;
      min-width: 0;
    }

    .had-tasks { overflow: auto; }

  }
</style>
