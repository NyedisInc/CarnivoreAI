
<script lang="ts">
    import { onMount } from 'svelte';
    import ManagerFrame from '../manager-frame/ManagerFrame.svelte';
    import { t as appT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import ChatWidget from '../../cplugs/huddle/chat/ChatWidget.svelte';
    import { chatSlotId } from '../../cplugs/huddle/chat/chat-model';
    import { agentIdFromHash, agentPage } from '../../cplugs/huddle/agents/agent-page.svelte';

    interface Props {
        t?: Translate;
        embedded?: boolean;
    }

    const { t = appT, embedded = false }: Props = $props();

    // svelte-ignore state_referenced_locally
    let open = $state(embedded);
    let opener: HTMLElement | null = null;
    let agentName = $state('');

    export function show(): void {
        const named = typeof location === 'undefined' ? null : agentIdFromHash(location.hash);
        if (named !== null) agentPage.id = named;
        if (!open) {
            const active = typeof document !== 'undefined' ? document.activeElement : null;
            opener = active instanceof HTMLElement ? active : null;
            open = true;
        }
    }

    export function close(): void {
        if (!open || embedded) return;
        open = false;
        if (opener && typeof document !== 'undefined' && document.contains(opener)) opener.focus();
        opener = null;
    }

    export function isOpen(): boolean {
        return open;
    }

    onMount(() => {
        if (embedded) show();
    });
</script>

{#if open}
    <ManagerFrame
        title={agentName || t('cplug.huddle.agents.page_title')}
        label={t('cplug.huddle.agents.page_label')}
        items={[]}
        status={{ kind: 'ready' }}
        query=""
        onQuery={() => {}}
        searchable={false}
        showCount={false}
        onClose={embedded ? undefined : close}
        {embedded}
        {t}
    >
        {#snippet body()}
            <div class="hdr-agent-page" data-huddle-agent-page={agentPage.id ?? undefined}>
                {#if agentPage.id !== null}
                    {#key agentPage.id}
                        <ChatWidget instance={chatSlotId(agentPage.id)} onOpenedTerminal={close} onName={(name) => (agentName = name)} titled />
                    {/key}
                {/if}
            </div>
        {/snippet}
    </ManagerFrame>
{/if}

<style>
  @layer components {
    .hdr-agent-page {
        display: flex;
        flex-direction: column;
        height: 100%;
        min-height: 0;
        min-width: 0;
        overflow: hidden;
    }
  }
</style>
