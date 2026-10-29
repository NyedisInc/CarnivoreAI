
<script lang="ts">
    import Button from '../base/Button.svelte';
    import { onDestroy } from 'svelte';
    import { t as reactiveT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import './panel-kit/panel-kit.css';
    import './phone-link/phone-link.css';
    import { countdown, rotateQr, type Fetcher, type PairWindow, type PairingView } from './phone-link/api';

    interface Props {
        window: PairWindow;
        pairing: PairingView;
        t?: Translate;
        fetcher?: Fetcher;
        onClose: () => void;
        onDone: () => void;
        onRevoke: (id: string) => void;
        onAgain: () => void;
    }
    const { window: win, pairing, t = reactiveT, fetcher, onClose, onDone, onRevoke, onAgain }: Props = $props();

    let left = $state(0);
    // svelte-ignore state_referenced_locally
    let qr = $state(win.qr);
    // svelte-ignore state_referenced_locally
    let qrExpires = $state(win.qr_expires_at);
    let showCode = $state(false);
    let confirmingRevoke = $state(false);
    let rotating = false;
    $effect(() => {
        qr = win.qr;
        qrExpires = win.qr_expires_at;
        showCode = false;
    });

    async function tick(): Promise<void> {
        const now = Date.now() / 1000;
        left = Math.max(0, win.expires_at - now);
        if (pairing.state === 'pending' || pairing.state === 'claimed' || left <= 0 || rotating || qrExpires - now >= win.qr_rotate_seconds) return;
        rotating = true;
        try {
            const next = await rotateQr(fetcher);
            qr = next.qr;
            qrExpires = next.qr_expires_at;
        } catch {
        } finally {
            rotating = false;
        }
    }
    void tick();
    const timer = setInterval(() => void tick(), 1000);
    const onVisible = (): void => {
        if (document.visibilityState === 'visible') void tick();
    };
    document.addEventListener('visibilitychange', onVisible);
    onDestroy(() => {
        clearInterval(timer);
        document.removeEventListener('visibilitychange', onVisible);
    });
</script>

<div class="pl-window" data-pl="window">
    {#if pairing.state === 'claimed' && pairing.device}
        <p class="tm__sub" data-pl="paired">{t('settings.phone_link.window.paired', { label: pairing.device.label })}</p>
        <div class="pl-window__actions">
            <Button variant="confirm" data-pl="done" onclick={onDone}>{t('settings.phone_link.window.done')}</Button>
            {#if confirmingRevoke}
                <Button size="sm" data-pl="paired-revoke-keep" onclick={() => (confirmingRevoke = false)}>{t('settings.phone_link.revoke_keep')}</Button>
                <Button variant="danger" size="sm" data-pl="paired-revoke-sure" onclick={() => onRevoke(pairing.device?.id ?? '')}>{t('settings.phone_link.revoke_sure')}</Button>
            {:else}
                <Button variant="danger" size="sm" data-pl="paired-revoke" onclick={() => (confirmingRevoke = true)}>{t('settings.phone_link.revoke')}</Button>
            {/if}
            <Button data-pl="again" onclick={onAgain}>{t('settings.phone_link.window.again')}</Button>
        </div>
    {:else if pairing.state === 'pending'}
        <p class="tm__sub" data-pl="scanned" role="status">{t('settings.phone_link.window.scanned')}</p>
        <div class="pl-window__actions">
            <Button data-pl="close" onclick={onClose}>{t('settings.phone_link.window.cancel')}</Button>
        </div>
    {:else if left <= 0}
        <p class="tm__sub" data-pl="countdown">{t('settings.phone_link.window.expired')}</p>
    {:else}
        <p class="tm__sub">{t('settings.phone_link.window.scan')}</p>
        <img class="pl-window__qr" src={qr} alt={t('settings.phone_link.window.qr_alt')} width="200" height="200" data-pl="qr" />
        <p class="tm__sub" data-pl="countdown">{t('settings.phone_link.window.expires', { time: countdown(left) })}</p>
        {#if showCode}
            <p class="tm__sub" data-pl="type-at">{t('settings.phone_link.window.type_at', { url: win.pair_url })}</p>
            <p class="pl-window__code" data-pl="code">{win.code}</p>
        {/if}
        <div class="pl-window__actions">
            {#if !showCode}
                <Button data-pl="show-code" onclick={() => (showCode = true)}>{t('settings.phone_link.window.show_code')}</Button>
            {/if}
            <Button data-pl="close" onclick={onClose}>{t('settings.phone_link.window.cancel')}</Button>
        </div>
    {/if}
</div>
