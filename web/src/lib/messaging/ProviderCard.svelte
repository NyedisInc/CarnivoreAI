
<script lang="ts">
    import { planFlow, planIdempotency } from './flow';
    import Check from '../../opscenter/ui/Check.svelte';
    import type { Translate } from '../sessions/types';
    import {
        createConversation, deleteConversation, deleteProvider, fetchProviderConversations, setProviderEnabled, testProvider,
        type Conversation, type Fetcher, type Provider, type ProviderConversation,
    } from './api';

    interface Props {
        t: Translate;
        provider: Provider;
        conversations: Conversation[];
        busy: boolean;
        act: (work: () => Promise<void>, done?: string) => Promise<boolean>;
        fetcher?: Fetcher;
    }
    const { t, provider, conversations, busy, act, fetcher }: Props = $props();

    let confirming = $state(false);
    let picking = $state<ProviderConversation[] | null>(null);
    let testTarget = $state('');

    const streamWord = $derived(t(`messaging.ui.stream.${provider.stream.state ?? 'stopped'}`));
    const gap = $derived(provider.stream.gap);
    const flow = $derived(planFlow(t, provider.stream));
    const idempotency = $derived(planIdempotency(t, provider.idempotency));

    const openPicker = (): Promise<boolean> => act(async () => { picking = await fetchProviderConversations(provider.id, fetcher); });

    const add = (entry: ProviderConversation): Promise<boolean> =>
        act(async () => { await createConversation(provider.id, entry.conversation, entry.label || entry.conversation, fetcher); picking = null; });
</script>

<div class="tm__srv" class:tm__srv--off={!provider.enabled} data-messaging-provider={provider.id}>
    <div class="tm__srv-head">
        <span class="tm__srv-name">{provider.name}</span>
        <span class="tm__sub" data-messaging="stream">{t('messaging.ui.provider.stream', { state: streamWord })}</span>
        <span class="tm__srv-tools">
            <Check label={t('messaging.ui.provider.enabled')} checked={provider.enabled} disabled={busy} data-messaging="enabled"
                onToggle={(next) => void act(async () => void (await setProviderEnabled(provider.id, next, fetcher)))} />
        </span>
    </div>
    <p class={flow.flowing ? 'tm__sub' : 'tm__problem'} data-messaging="flow" data-flow={provider.stream.flow}>{flow.flowText}</p>
    <p class="tm__sub" data-messaging="traffic">{flow.trafficText}</p>
    <p class={idempotency.proven ? 'tm__sub' : 'messaging-held'} data-messaging="idempotency" data-proven={idempotency.proven}>{idempotency.text}</p>
    {#if flow.bridgeText}<p class="tm__sub" data-messaging="bridge">{flow.bridgeText}</p>{/if}
    {#if gap}<p class="tm__problem" role="status" data-messaging="gap">{t('messaging.ui.provider.gap', { after: gap.after, oldest: gap.oldest })}</p>{/if}
    <p class="tm__sub" data-messaging="secrets">{t('messaging.ui.provider.secrets', {
        url: t(provider.secrets.base_url?.set ? 'messaging.ui.set' : 'messaging.ui.unset'),
        token: t(provider.secrets.token?.set ? 'messaging.ui.set' : 'messaging.ui.unset'),
        count: provider.secrets.owner_senders?.count ?? 0,
    })}</p>

    <span class="oc-key">{t('messaging.ui.conversations.title')}</span>
    {#each conversations as conv (conv.id)}
        <div class="tm__srv-head" data-messaging-conversation={conv.id}>
            <span class="tm__srv-name">{conv.label}</span>
            <span class="tm__srv-tools">
                <button type="button" class="oc-btn oc-btn--ghost" disabled={busy} data-messaging="conversation-remove"
                    onclick={() => void act(async () => void (await deleteConversation(conv.id, fetcher)))}>{t('messaging.ui.conversations.remove')}</button>
            </span>
        </div>
    {/each}
    {#if conversations.length === 0}<p class="tm__sub" data-messaging="no-conversations">{t('messaging.ui.conversations.none')}</p>{/if}
    {#if picking}
        <div class="tm__srv" data-messaging="picker">
            {#each picking as entry (entry.conversation)}
                <div class="tm__srv-head">
                    <span class="tm__srv-name">{entry.label || t('messaging.ui.conversations.unnamed')}</span>
                    <span class="tm__srv-tools">
                        {#if entry.routable}
                            <button type="button" class="oc-btn oc-btn--confirm" disabled={busy} data-messaging="picker-add" onclick={() => void add(entry)}>{t('messaging.ui.conversations.add_this')}</button>
                        {:else}
                            <span class="tm__sub" data-messaging="picker-not-routable">{t('messaging.ui.conversations.not_routable')}</span>
                        {/if}
                    </span>
                </div>
            {/each}
            {#if picking.length === 0}<p class="tm__sub">{t('messaging.ui.conversations.provider_none')}</p>{/if}
            <div class="tm__actions"><button type="button" class="modal-btn modal-btn-secondary" onclick={() => (picking = null)}>{t('messaging.ui.cancel')}</button></div>
        </div>
    {/if}

    <div class="tm__actions">
        <button type="button" class="oc-btn oc-btn--ghost" disabled={busy || !provider.enabled} data-messaging="picker-open" onclick={() => void openPicker()}>{t('messaging.ui.conversations.add')}</button>
        {#if conversations.length > 0}
            <select class="oc-field" bind:value={testTarget} disabled={busy} aria-label={t('messaging.ui.provider.test_target')} data-messaging="test-target">
                <option value="">{t('messaging.ui.provider.test_target')}</option>
                {#each conversations as conv (conv.id)}<option value={conv.id}>{conv.label}</option>{/each}
            </select>
            <button type="button" class="oc-btn oc-btn--ghost" disabled={busy || !testTarget} data-messaging="test"
                onclick={() => void act(async () => void (await testProvider(provider.id, testTarget, fetcher)), t('messaging.ui.provider.test_sent'))}>{t('messaging.ui.provider.test')}</button>
        {/if}
        {#if confirming}
            <button type="button" class="modal-btn modal-btn-secondary" data-messaging="remove-cancel" onclick={() => (confirming = false)}>{t('messaging.ui.cancel')}</button>
            <button type="button" class="modal-btn modal-btn-danger" disabled={busy} data-messaging="remove-confirm"
                onclick={() => void act(async () => void (await deleteProvider(provider.id, fetcher)))}>{t('messaging.ui.provider.remove_confirm')}</button>
        {:else}
            <button type="button" class="oc-btn oc-btn--ghost" disabled={busy} data-messaging="remove" onclick={() => (confirming = true)}>{t('messaging.ui.provider.remove')}</button>
        {/if}
    </div>
</div>
