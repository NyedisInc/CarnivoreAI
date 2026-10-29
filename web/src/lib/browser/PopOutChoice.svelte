
<script lang="ts">
    import { onMount, tick } from 'svelte';
    import { t } from '../i18n/index.svelte';
    import { Button, IconButton } from '../base';
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

    let proxyButton = $state<HTMLElement | null>(null);
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
            <IconButton variant="close" icon="close" label={t('modal.close')} onclick={() => close(null)} />
        </div>
    {/snippet}
    <p class="modal-description" id="browser-popout-question">{t('browser.popout.question')}</p>
    <p class="modal-description" data-popout-proxy-hint>{t('browser.popout.proxy_hint')}</p>
    <p class="modal-description" data-popout-real-hint>{realHint}</p>
    {#if reach.ok && shortened}
        <p class="modal-description" data-popout-shortened>{t('browser.popout.shortened')}</p>
    {/if}
    {#snippet footer()}
        <Button data-popout-cancel onclick={() => close(null)}>{t('browser.popout.cancel')}</Button>
        <Button variant="confirm" data-popout-choice="real" disabled={!reach.ok}
            onclick={() => take('real')} onkeydown={(e) => onChoiceKey(e, 'real')}>{t('browser.popout.real')}</Button>
        <Button variant="confirm" data-popout-choice="proxy" bind:element={proxyButton}
            onclick={() => take('proxy')} onkeydown={(e) => onChoiceKey(e, 'proxy')}>{t('browser.popout.proxy')}</Button>
    {/snippet}
</ModalShell>
