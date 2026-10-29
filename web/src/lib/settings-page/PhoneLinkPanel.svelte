
<script lang="ts">
    import Button from '../base/Button.svelte';
    import List from '../base/List.svelte';
    import ListRow from '../base/ListRow.svelte';
    import State from '../base/State.svelte';
    import Switch from '../base/Switch.svelte';
    import { onDestroy, onMount } from 'svelte';
    import { t as reactiveT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import './panel-kit/panel-kit.css';
    import './phone-link/phone-link.css';
    import { ApiError } from '../../opscenter/api/auth.svelte';
    import { errorText } from './panel-kit/error-text';
    import PairWindowView from './PairWindow.svelte';
    import CustomDomain from './CustomDomain.svelte';
    import { isAccountLoaded, isSignedIn, refreshAccount } from '../carnivore-account/account-store.svelte';
    import { requireAccount } from '../carnivore-account/funnel';
    import {
        closeWindow,
        listDevices,
        getStatus,
        acknowledgeFailures,
        openWindow,
        revokeDevice,
        setEnabled,
        utcMinute,
        type Device,
        type Fetcher,
        type LinkStatus,
        type PairWindow,
    } from './phone-link/api';

    interface Props {
        t?: Translate;
        fetcher?: Fetcher;
    }
    const { t = reactiveT, fetcher }: Props = $props();

    const REFRESH_MS = 3000;

    let status = $state<LinkStatus | null>(null);
    let devices = $state<Device[]>([]);
    let win = $state<PairWindow | null>(null);
    let busy = $state(false);
    let problem = $state('');
    let note = $state('');
    let overLink = $state(false);

    const locked = $derived(isAccountLoaded() && !isSignedIn());
    if (!isAccountLoaded()) void refreshAccount();

    const gated = (work: () => Promise<void>): Promise<void> =>
        locked ? requireAccount({ feature: 'phone_link', src: 'phone_link', resume: () => void work() }).then(() => undefined) : work();

    let sawPending = false;

    async function followPairing(state: LinkStatus['pairing']['state']): Promise<void> {
        if (state === 'pending') sawPending = true;
        else if (state === 'none' && sawPending) {
            sawPending = false;
            win = await openWindow(fetcher);
            note = t('settings.phone_link.window.retry');
        } else if (state === 'failed') {
            sawPending = false;
            win = null;
        } else if (state === 'claimed') sawPending = false;
    }

    function endWindow(): void {
        win = null;
        sawPending = false;
        void closeWindow(fetcher).catch(() => undefined);
    }

    async function load(): Promise<void> {
        try {
            status = await getStatus(fetcher);
            devices = await listDevices(fetcher);
            if (win) await followPairing(status.pairing.state);
            problem = '';
        } catch (error) {
            if (error instanceof ApiError && error.status === 403 && error.code === 'account_required') {
                return;
            }
            if (error instanceof ApiError && error.status === 403) {
                overLink = true;
                clearInterval(timer);
                return;
            }
            problem = errorText(error);
        }
    }
    void load();
    const timer = setInterval(() => void load(), REFRESH_MS);
    onDestroy(() => {
        clearInterval(timer);
        if (win) void closeWindow(fetcher, true).catch(() => undefined);
    });

    async function act(work: () => Promise<void>): Promise<void> {
        busy = true;
        problem = '';
        note = '';
        try {
            await work();
        } catch (error) {
            problem = errorText(error);
        } finally {
            busy = false;
        }
        await load();
    }

    const toggle = (next: boolean) => {
        const work = () =>
            act(async () => {
                status = await setEnabled(next, fetcher);
                if (!next) win = null;
            });
        return next ? gated(work) : work();
    };
    const pair = () =>
        gated(() =>
            act(async () => {
                sawPending = false;
                win = await openWindow(fetcher);
            }),
        );
    const retry = () =>
        gated(() =>
            act(async () => {
                sawPending = false;
                await acknowledgeFailures(fetcher);
                win = await openWindow(fetcher);
            }),
        );
    const revoke = (id: string) =>
        act(async () => {
            await revokeDevice(id, fetcher);
            note = t('settings.phone_link.revoked');
        });

    const TUNNEL_STATES = ['stopped', 'connecting', 'connected', 'denied', 'update_required'];

    const tunnelText = (s: LinkStatus): string =>
        (TUNNEL_STATES.includes(s.tunnel) ? t(`settings.phone_link.tunnel.${s.tunnel}`) : s.tunnel) + (s.error ? `: ${s.error}` : '');

    const seenText = (d: Device): string =>
        d.last_seen ? t('settings.phone_link.seen', { at: utcMinute(d.last_seen) }) : t('settings.phone_link.never_seen');

    function pushText(d: Device): string {
        if (d.push.length === 0) return t('settings.phone_link.push.none');
        return d.push
            .map((p) =>
                p.last_result
                    ? t('settings.phone_link.push.last', { status: p.last_result.status, at: p.last_result.at.slice(0, 16).replace('T', ' ') })
                    : t('settings.phone_link.push.never'),
            )
            .join(', ');
    }
</script>

{#if !overLink}
<div class="tm" data-pl="panel">
    {#if status && locked && !status.enabled}
        <div class="pl-signin" data-pl="signin">
            <p class="tm__sub">{t('settings.phone_link.signin.hint')}</p>
            <Button variant="confirm" data-pl="signin-btn" onclick={() => void gated(() => act(async () => { status = await setEnabled(true, fetcher); }))}>
                {t('account.lock.cta')}
            </Button>
        </div>
    {:else if status}
        <Switch label={t('settings.phone_link.switch')} bind:checked={() => status?.enabled ?? false, (next) => void toggle(next)} disabled={busy}
            data-pl="switch" />
        <p class="tm__sub">{t('settings.phone_link.hint')}</p>
        {#if locked}<p class="tm__sub" data-pl="grace">{t('settings.phone_link.signin.grace')}</p>{/if}

        <dl class="pl-facts" data-pl="facts">
            <dt>{t('settings.phone_link.cert')}</dt>
            <dd data-pl="cert">
                {#if status.cert}
                    {t('settings.phone_link.cert.value', {
                        issuer: status.cert.issuer,
                        expiry: status.cert.not_after.slice(0, 10),
                        environment: t(`settings.phone_link.env.${status.cert.environment}`),
                    })}
                {:else}
                    {t('settings.phone_link.cert.none')}
                {/if}
            </dd>
            <dt>{t('settings.phone_link.tunnel')}</dt>
            <dd data-pl="tunnel">{tunnelText(status)}</dd>
        </dl>

        {#if win}
            <PairWindowView window={win} pairing={status.pairing} {t} {fetcher} onClose={endWindow} onDone={endWindow}
                onRevoke={(id) => { endWindow(); void revoke(id); }} onAgain={() => void pair()} />
        {:else}
            {#if status.pairing.state === 'failed'}
                <State kind="error" inline data-pl="failed"
                    title={t(status.pairing.locked ? 'settings.phone_link.window.failed_locked' : 'settings.phone_link.window.failed')}>
                    {#snippet actions()}
                        <Button variant="confirm" data-pl="retry" disabled={busy || !status?.enabled} onclick={() => void retry()}>
                            {t('settings.phone_link.window.try_again')}
                        </Button>
                    {/snippet}
                </State>
            {:else}
            <div>
                <Button variant="confirm" data-pl="pair" disabled={busy || !status.enabled} onclick={() => void pair()}>
                    {t('settings.phone_link.pair')}
                </Button>
            </div>
            {/if}
        {/if}

    {/if}
    {#if status}
        {#if devices.length > 0}
            <List label={t('settings.phone_link.switch')} data-pl="devices">
                {#snippet children()}
                    {#each devices as d (d.id)}
                        <ListRow wrap data-pl-device={d.id} primary={d.label}>
                            {#snippet actions()}
                                <Button variant="danger" size="sm" data-pl="revoke" disabled={busy} onclick={() => void revoke(d.id)}>
                                    {t('settings.phone_link.revoke')}
                                </Button>
                            {/snippet}
                            {#snippet below()}
                                <span>{seenText(d)}</span>
                                <span data-pl="push">{pushText(d)}</span>
                            {/snippet}
                        </ListRow>
                    {/each}
                {/snippet}
            </List>
        {:else}
            <p class="tm__sub" data-pl="empty">{t('settings.phone_link.empty')}</p>
        {/if}
        <CustomDomain {t} {fetcher} part="main" />
    {:else if !problem}
        <p class="tm__sub">{t('settings.phone_link.loading')}</p>
    {/if}
    {#if note}<State inline title={note} role="status" data-pl="note" />{/if}
    {#if problem}<State kind="error" inline title={problem} data-pl="problem" />{/if}
</div>
{/if}
