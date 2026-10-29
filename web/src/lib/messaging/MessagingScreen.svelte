<!-- settings > notifications > messaging -->
<script lang="ts">
    import { onMount } from 'svelte';
    import { t as reactiveT } from '../i18n/index.svelte';
    import { Button } from '../base';
    import type { Translate } from '../sessions/types';
    import '../settings-page/panel-kit/panel-kit.css';
    import './messaging.css';
    import { createProvider, retryMessage, type Fetcher, type ProviderBody } from './api';
    import BindingRows from './BindingRows.svelte';
    import { planLogRow } from './log-row';
    import ProviderCard from './ProviderCard.svelte';
    import ProviderForm from './ProviderForm.svelte';
    import { attach, messaging, problemText, refresh } from './store.svelte';

    interface Props {
        t?: Translate;
        fetcher?: Fetcher;
    }
    const { t = reactiveT, fetcher }: Props = $props();

    let adding = $state(false);
    let busy = $state(false);
    let problem = $state('');
    let note = $state('');

    onMount(() => attach(fetcher));

    async function act(work: () => Promise<void>, done = ''): Promise<boolean> {
        busy = true;
        problem = '';
        note = '';
        try {
            await work();
            note = done;
            return true;
        } catch (error) {
            problem = problemText(error, t);
            return false;
        } finally {
            busy = false;
            await refresh();
        }
    }

    async function save(body: ProviderBody): Promise<void> {
        if (await act(async () => void (await createProvider(body, fetcher)), t('messaging.ui.provider.saved'))) adding = false;
    }

    const when = (epoch: number): string => new Date(epoch * 1000).toLocaleString();
</script>

<div class="tm" data-messaging="screen">
    <p class="tm__sub">{t('messaging.ui.intro')}</p>

    <span class="oc-key">{t('messaging.ui.providers.title')}</span>
    {#each messaging.providers as provider (provider.id)}
        <ProviderCard {t} {provider} conversations={messaging.conversations.filter((c) => c.provider_id === provider.id)} bindings={messaging.bindings} {busy} {act} {fetcher} />
    {/each}
    {#if messaging.loaded && messaging.providers.length === 0}<p class="tm__sub" data-messaging="no-providers">{t('messaging.ui.providers.none')}</p>{/if}
    {#if adding}
        <ProviderForm {t} {busy} onSave={(b) => void save(b)} onCancel={() => (adding = false)} />
    {:else}
        <div class="tm__actions">
            <Button variant="confirm" disabled={busy} data-messaging="provider-add" onclick={() => (adding = true)}>{t('messaging.ui.provider.add')}</Button>
        </div>
    {/if}

    <span class="oc-key">{t('messaging.ui.bindings.title')}</span>
    <p class="tm__sub">{t('messaging.ui.bindings.hint')}</p>
    <BindingRows {t} bindings={messaging.bindings} conversations={messaging.conversations} {busy} {act} {fetcher} />

    <span class="oc-key">{t('messaging.ui.log.title')}</span>
    <div class="messaging-rows" data-messaging="log">
        {#each messaging.messages as m (m.id)}
            {@const row = planLogRow(t, m)}
            <div class="messaging-row" data-messaging-message={m.id}>
                <span class="tm__sub">{when(m.received_at)}</span>
                <span class="tm__sub">{t(`messaging.ui.log.${m.direction}`)}</span>
                <span class="messaging-log__status" data-status={m.status}>{row.statusText}</span>
                {#if row.hint}<span class="tm__sub" data-messaging="unconfirmed-hint">{row.hint}</span>{/if}
                <span class="messaging-log__text">{m.text}</span>
                {#if row.retry}
                    <Button variant="quiet" size="sm" disabled={busy} data-messaging="retry"
                        onclick={() => void act(async () => void (await retryMessage(m.id, fetcher)))}>{t('messaging.ui.log.retry')}</Button>
                {/if}
            </div>
        {/each}
        {#if messaging.loaded && messaging.messages.length === 0}<p class="tm__sub" data-messaging="no-messages">{t('messaging.ui.log.none')}</p>{/if}
    </div>

    {#if note}<p class="tm__note" role="status" data-messaging="note">{note}</p>{/if}
    {#if problem}<p class="tm__problem" role="alert" data-messaging="problem">{problem}</p>{/if}
    {#if messaging.problem}<p class="tm__problem" role="alert" data-messaging="load-problem">{messaging.problem}</p>{/if}
</div>
