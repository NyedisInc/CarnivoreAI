
<script lang="ts">
    import { onMount } from 'svelte';
    import { t as reactiveT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import '../settings-page/panel-kit/panel-kit.css';
    import './byoai.css';
    import { errorText } from '../settings-page/panel-kit/error-text';
    import { isStale, putDefault, putFeature, type Fetcher, type TargetRef } from './api';
    import { ai, attach, refresh } from './store.svelte';
    import RouteRow from './RouteRow.svelte';
    import Icon from '../../opscenter/ui/Icon.svelte';

    interface Props {
        t?: Translate;
        fetcher?: Fetcher;
    }
    const { t = reactiveT, fetcher }: Props = $props();

    const CAPABILITIES = ['chat', 'embed', 'decide', 'agent', 'speak', 'transcribe', 'image', 'video', 'audio'] as const;

    let busy = $state(false);
    let problem = $state('');
    let note = $state('');
    let overridesOpen = $state(false);

    onMount(() => attach(fetcher));

    async function act(work: (revision: number) => Promise<unknown>): Promise<void> {
        busy = true;
        problem = '';
        note = '';
        try {
            await work(ai.config?.revision ?? 0);
            note = t('settings.ai.saved');
        } catch (error) {
            problem = isStale(error) ? t('settings.ai.stale') : errorText(error);
        } finally {
            busy = false;
            await refresh();
        }
    }

    const setDefault = (capability: string, target: TargetRef | null): Promise<void> => act((rev) => putDefault(capability, target, rev, fetcher));
    const setFeature = (id: string, target: TargetRef | null): Promise<void> => act((rev) => putFeature(id, target, rev, fetcher));

    const own = $derived(ai.features.filter((f) => !f.hidden && !f.owner));
    const addons = $derived(ai.features.filter((f) => !f.hidden && !!f.owner));
</script>

<div class="tm" data-ai="routing">
    <p class="tm__sub">{t('settings.ai.routing.intro')}</p>
    {#if ai.config}
        <div data-ai="defaults">
            {#each CAPABILITIES as capability (capability)}
                {#key JSON.stringify(ai.config.defaults[capability] ?? null)}
                    <RouteRow {t} name={t(`settings.ai.capability.${capability}`)} {capability} target={ai.config.defaults[capability] ?? null} {busy}
                        onSet={(target) => void setDefault(capability, target)} onClear={() => void setDefault(capability, null)} />
                {/key}
            {/each}
        </div>
        <p class="oc-key">{t('settings.ai.routing.features')}</p>
        <div data-ai="features">
            {#each own as feature (feature.id)}
                {#key JSON.stringify(feature.target)}
                    <RouteRow {t} name={t(feature.label_key)} capability={feature.capability} target={feature.target} {busy}
                        onSet={(target) => void setFeature(feature.id, target)} onClear={() => void setFeature(feature.id, null)} />
                {/key}
            {/each}
            {#if ai.features.length === 0}<p class="tm__sub" data-ai="features-none">{t('settings.ai.routing.features_none')}</p>{/if}
        </div>
        {#if addons.length > 0}
            <button type="button" class="rtp-fold oc-key" data-ai="addons-head" aria-expanded={overridesOpen}
                onclick={() => (overridesOpen = !overridesOpen)}>
                <Icon name={overridesOpen ? 'chevron-down' : 'chevron-right'} size={12} />
                {t('settings.ai.routing.addons', { count: addons.length })}
                <span class="tm__sub">{t('settings.ai.routing.addons_note')}</span>
            </button>
            {#if overridesOpen}
                <div data-ai="addon-features">
                    {#each addons as feature (feature.id)}
                        {#key JSON.stringify(feature.target)}
                            <RouteRow {t} name={t(feature.label_key)} href={feature.owner?.href ?? null} capability={feature.capability} target={feature.target} {busy}
                                onSet={(target) => void setFeature(feature.id, target)} onClear={() => void setFeature(feature.id, null)} />
                        {/key}
                    {/each}
                </div>
            {/if}
        {/if}
    {:else if !ai.problem}
        <p class="tm__sub">{t('settings.ai.loading')}</p>
    {/if}
    {#if note}<p class="tm__note" role="status" data-ai="note">{note}</p>{/if}
    {#if problem || ai.problem}<p class="tm__problem" role="alert" data-ai="problem">{problem || ai.problem}</p>{/if}
</div>

<style>
    .rtp-fold {
        display: flex;
        align-items: center;
        gap: var(--oc-space-2);
        width: 100%;
        padding: 0;
        border: 0;
        background: transparent;
        text-align: left;
        cursor: pointer;
    }
</style>
