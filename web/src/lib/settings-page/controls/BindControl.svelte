
<script lang="ts">
    import Field from '../../base/Field.svelte';
    import type { Translate } from '../../sessions/types';
    import { bindState, settingsDoc } from '../settings-doc.svelte';

    interface Props {
        t: Translate;
        inputId: string;
    }

    const { t, inputId }: Props = $props();

    const prefs = $derived(settingsDoc.summary?.server_prefs ?? {});
    const server = $derived(settingsDoc.summary?.server ?? {});
    const saved = $derived(prefs.bind_host ?? '');
    const effective = $derived(prefs.effective_bind_host ?? '');
    const state = $derived(bindState(saved, effective));
    const value = $derived(String(settingsDoc.value('bind_address') ?? ''));
</script>

<Field
    id={inputId}
    block
    placeholder="127.0.0.1"
    spellcheck={false}
    {value}
    oninput={(event) => settingsDoc.setDraft('bind_address', (event.currentTarget as HTMLInputElement).value)}
/>
<div class="st-facts">
    <p class="sf__hint" data-bind-state={state}>
        {#if state === 'unmeasured'}
            {saved ? t('settings.bind.unmeasured_saved', { saved }) : t('settings.bind.unmeasured')}
        {:else if state === 'unset'}
            {t('settings.bind.unset', { effective })}
        {:else if state === 'in-force'}
            {t('settings.bind.in_force', { effective })}
        {/if}
    </p>
    {#if state === 'pending'}
        <p class="sf__error" data-bind-state="pending">{t('settings.bind.pending', { effective })}</p>
    {/if}
    {#if server.host !== undefined}
        <p class="sf__hint">{t('settings.bind.env_host', { host: server.host || t('settings.bind.env_host_empty') })}</p>
    {/if}
    {#if server.wildcard_bind}
        <p class="sf__error" data-bind-wildcard>{t('settings.bind.wildcard')}</p>
    {/if}
</div>
