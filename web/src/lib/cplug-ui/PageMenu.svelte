
<script lang="ts">
    import { phoneFlag } from '../drawer/phone-flag.svelte';
    import { t } from '../i18n/index.svelte';
    import { pageOf, pageSteps, showStep } from './page-views.svelte';
    import ViewFrame from './ViewFrame.svelte';

    let { tabId }: { tabId?: string } = $props();

    const entry = $derived(tabId ? pageOf(tabId) : undefined);
    const step = $derived((tabId && pageSteps[tabId]) || 'menu');
    const phone = $derived(phoneFlag.value);

</script>

<div class="cu-page" data-page-menu data-page-phone={phone ? '' : undefined}>
    {#if entry}
        {#key entry.key}
            <div class="cu-page__step" data-page-step="menu" hidden={phone && step !== 'menu'}>
                <ViewFrame plugin={entry.plugin} view={entry.menu} surface="panel" viewRole="menu" visible={!phone || step === 'menu'} onShow={() => tabId && phone && showStep(tabId, 'view')} {t} />
            </div>
            {#if phone}
                <div class="cu-page__step" data-page-step="view" hidden={step !== 'view'}>
                    <ViewFrame plugin={entry.plugin} view={entry.main} surface="panel" viewRole="page" visible={step === 'view'} {t} />
                </div>
            {/if}
        {/key}
    {:else}
        <p class="cu-page__off" role="status">{t('cplug_ui.panel_off')}</p>
    {/if}
</div>
