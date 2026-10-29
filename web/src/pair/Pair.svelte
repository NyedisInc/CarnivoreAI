
<script lang="ts">
    import { onMount } from 'svelte';
    import { t } from '../lib/i18n/index.svelte';
    import { Button, Field } from '../lib/base';
    import { claimSecret, isInstalledApp, keepSession, navigate, pairStatus, submitCode, verifyOtp, type ClaimResult, type Failure } from './pair-api';

    type Phase = 'checking' | 'claiming' | 'otp' | 'done' | 'scan' | 'entry';

    let phase = $state<Phase>('checking');
    let failure = $state<Failure | null>(null);
    let typed = $state('');
    let otp = $state('');
    let busy = $state(false);
    let showForm = $state(false);
    const installed = isInstalledApp();

    function enter(): void {
        phase = 'done';
        navigate.to('/');
    }

    function afterClaim(result: ClaimResult): boolean {
        if (!result.ok) return false;
        if (result.status === 'already_paired') enter();
        else phase = 'otp';
        return true;
    }

    onMount(async () => {
        const secret = location.hash.slice(1);
        if (secret) {
            history.replaceState(null, '', location.pathname);
            phase = 'claiming';
            const result = await claimSecret(secret);
            if (afterClaim(result)) return;
            failure = result.ok ? null : result.failure;
        } else {
            const now = await pairStatus();
            if (now.paired) return enter();
            if (now.pending) {
                phase = 'otp';
                return;
            }
        }
        phase = installed ? 'entry' : 'scan';
    });

    async function submit(event: Event): Promise<void> {
        event.preventDefault();
        busy = true;
        failure = null;
        const result = await submitCode(typed);
        busy = false;
        if (!afterClaim(result) && !result.ok) failure = result.failure;
    }

    async function finish(event: Event): Promise<void> {
        event.preventDefault();
        busy = true;
        failure = null;
        const result = await verifyOtp(otp);
        busy = false;
        if (result.ok) {
            keepSession(result.accessToken, result.refreshToken);
            enter();
            return;
        }
        failure = result.failure;
        otp = '';
        if (result.failure === 'pairing_dead') phase = installed ? 'entry' : 'scan';
    }
</script>

<main class="pair" data-pair={phase}>
    <header class="pair__bar"><span class="pair__label">{t('pair.title')}</span></header>
    <div class="pair__body">
        {#if phase === 'claiming'}
            <p class="pair__text" role="status" data-pair="claiming">{t('pair.claiming', { host: location.hostname })}</p>
        {:else if phase === 'otp'}
            <h1 class="pair__head">{t('pair.otp.heading')}</h1>
            <p class="pair__sub">{t('pair.otp.hint')}</p>
            <form class="pair__form" onsubmit={finish}>
                <label class="pair__sub" for="pair-otp">{t('pair.otp.label')}</label>
                <Field id="pair-otp" bind:value={otp} maxlength={6} inputmode="numeric"
                    pattern="[0-9]*" autocomplete="one-time-code" autocorrect="off" spellcheck={false} data-pair="otp-code" disabled={busy} />
                <Button type="submit" variant="confirm" data-pair="otp-submit" disabled={busy || otp.trim().length !== 6}>
                    {busy ? t('pair.entry.working') : t('pair.entry.submit')}
                </Button>
            </form>
        {:else if phase === 'done'}
            <p class="pair__text" role="status" data-pair="paired">{t('pair.done')}</p>
        {:else if phase === 'scan' || phase === 'entry'}
            <h1 class="pair__head">{phase === 'entry' ? t('pair.app.heading') : t('pair.scan.heading')}</h1>
            <p class="pair__sub">{phase === 'entry' ? t('pair.app.hint') : t('pair.scan.hint')}</p>
            <p class="pair__sub" data-pair="per-address-hint">{t('pair.per_address_hint')}</p>
            {#if phase === 'scan' && !showForm}
                <Button data-pair="no-camera" onclick={() => (showForm = true)}>{t('pair.scan.no_camera')}</Button>
            {/if}
            {#if phase === 'entry' || showForm}
                <form class="pair__form" onsubmit={submit}>
                    <label class="pair__sub" for="pair-code">{t('pair.entry.label')}</label>
                    <Field id="pair-code" bind:value={typed} maxlength={8} inputmode="text"
                        autocomplete="one-time-code" autocapitalize="characters" autocorrect="off" spellcheck={false}
                        data-pair="code" disabled={busy} />
                    <Button type="submit" variant="confirm" data-pair="submit" disabled={busy || typed.trim().length === 0}>
                        {busy ? t('pair.entry.working') : t('pair.entry.submit')}
                    </Button>
                </form>
            {/if}
        {/if}
        {#if failure}<p class="pair__problem" role="alert" data-pair-error={failure}>{t(`pair.error.${failure}`)}</p>{/if}
    </div>
</main>
