
<script lang="ts">
    import Segmented from '../base/Segmented.svelte';
    import { phoneFlag } from '../drawer/phone-flag.svelte';
    import { t } from '../i18n/index.svelte';
    import { pageSteps, showStep, type PageStep } from './page-views.svelte';

    let { tabId }: { tabId?: string } = $props();

    const phone = $derived(phoneFlag.value);
    const step = $derived<PageStep>((tabId && pageSteps[tabId]) || 'menu');
    const options = $derived((['menu', 'view'] as const).map((value) => ({ value, label: t(`cplug_ui.page.step_${value}`), attrs: { 'data-page-step-key': value } })));

</script>

{#if phone && tabId}
    <Segmented label={t('cplug_ui.page.steps')} bind:value={() => step, (next) => showStep(tabId, next as PageStep)} {options} data-page-switch />
{/if}
