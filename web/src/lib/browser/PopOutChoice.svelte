
<script lang="ts">
    import { onMount, tick } from 'svelte';
    import { t } from '../i18n/index.svelte';
    import ModalShell from '../launchpad/ModalShell.svelte';
    import type { RealPageReach } from './pop-out-reach';

    type Choice = 'proxy' | 'real';

    interface Props {
        label: string;
        proxyUrl: string;
        reach: RealPageReach;
        shortened: boolean;
        openTab: (url: string) => void;
        close: (value: Choice | null) => void;
    }

    const { label, proxyUrl, reach, shortened, openTab, close }: Props = $props();

    let proxyButton = $state<HTMLButtonElement | null>(null);
    const title = $derived(t('browser.popout.title', { label }));
    const realHint = $derived(
        reach.ok
            ? t('browser.popout.real_hint', { url: reach.url })
            : reach.reason === 'host_only' ? t('browser.popout.host_only') : t('browser.popout.no_address'),
    );

    function take(choice: Choice): void {
        if (choice === 'real') {
            if (!reach.ok) return;
            openTab(reach.url);
        } else {
            openTab(proxyUrl);
        }
        close(choice);
    }

    function onChoiceKey(event: KeyboardEvent, choice: Choice): void {
        if (event.key !== 'Enter') return;
        event.preventDefault();
        take(choice);
    }

    onMount(() => {
        void tick().then(() => proxyButton?.focus());
    });
</script>

<ModalShell {title} overlayClass="text-prompt-modal" describedby="browser-popout-question" onCancel={() => close(null)}>
    {#snippet head()}
        <div class="text-prompt-modal__head">
            <span class="text-prompt-modal__verb">&raquo; {title}</span>
            <button type="button" class="modal-close" aria-label={t('modal.close')} onclick={() => close(null)}>&times;</button>
        </div>
    {/snippet}
    <p class="modal-description" id="browser-popout-question">{t('browser.popout.question')}</p>
    <p class="modal-description" data-popout-proxy-hint>{t('browser.popout.proxy_hint')}</p>
    <p class="modal-description" data-popout-real-hint>{realHint}</p>
    {#if reach.ok && shortened}
        <p class="modal-description" data-popout-shortened>{t('browser.popout.shortened')}</p>
    {/if}
    {#snippet footer()}
        <button type="button" class="modal-btn modal-btn-secondary" data-popout-cancel onclick={() => close(null)}>{t('browser.popout.cancel')}</button>
        <button type="button" class="modal-btn modal-btn-confirm" data-popout-choice="real" disabled={!reach.ok}
            onclick={() => take('real')} onkeydown={(e) => onChoiceKey(e, 'real')}>{t('browser.popout.real')}</button>
        <button type="button" class="modal-btn modal-btn-confirm" data-popout-choice="proxy" bind:this={proxyButton}
            onclick={() => take('proxy')} onkeydown={(e) => onChoiceKey(e, 'proxy')}>{t('browser.popout.proxy')}</button>
    {/snippet}
</ModalShell>

<style>
    .modal-btn:disabled {
        opacity: 0.45;
        cursor: not-allowed;
    }
</style>
