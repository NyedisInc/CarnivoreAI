
<script lang="ts">
    import Button from '../base/Button.svelte';
    import State from '../base/State.svelte';
    import Switch from '../base/Switch.svelte';
    import { onDestroy } from 'svelte';
    import { t as reactiveT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import './panel-kit/panel-kit.css';
    import { authFetch } from '../../opscenter/api/auth.svelte';
    import { resourcePush } from '../resource-push/boot';
    import { errorText } from './panel-kit/error-text';

    interface UpdateStatus {
        attached: boolean;
        state: string;
        current_version: string;
        latest_version: string;
        percent: number | null;
        detail: string | null;
        auto_update: boolean;
    }

    interface Props {
        t?: Translate;
        fetcher?: typeof authFetch;
        pollMs?: number;
    }
    const { t = reactiveT, fetcher = authFetch, pollMs = 30000 }: Props = $props();

    const ROUTE = '/app-update';
    const KNOWN = ['not_configured', 'invalid_feed', 'idle', 'checking', 'available', 'downloading', 'ready', 'current', 'unknown', 'error', 'update_refused'];

    let status = $state<UpdateStatus | null>(null);
    let busy = $state(false);
    let problem = $state('');

    const phase = $derived(status ? (KNOWN.includes(status.state) ? status.state : 'unavailable') : '');
    const version = $derived(status?.latest_version ?? '');
    const canInstall = $derived(status?.attached === true && (phase === 'available' || phase === 'ready'));
    const working = $derived(phase === 'checking' || phase === 'downloading');

    async function load(): Promise<void> {
        try {
            status = await fetcher<UpdateStatus>(ROUTE);
            problem = '';
        } catch (error) {
            problem = errorText(error);
        }
    }
    void load();
    const stop = resourcePush().pushOrPoll(() => void load(), pollMs, ['app_update']);
    onDestroy(stop);

    async function act(path: string, init: { method: string; body?: string }): Promise<void> {
        busy = true;
        problem = '';
        try {
            status = await fetcher<UpdateStatus>(`${ROUTE}${path}`, init);
        } catch (error) {
            problem = errorText(error);
        } finally {
            busy = false;
        }
    }
</script>

<div class="tm" data-app-update="panel">
    {#if status}
        {#if status.current_version}
            <p class="tm__sub" data-app-update="version">{t('settings.app_update.version', { version: status.current_version })}</p>
        {/if}
        <p class="tm__sub" role="status" data-app-update="state">
            {t(`settings.app_update.state.${phase}`, { version, percent: status.percent ?? 0, detail: status.detail ?? '' })}
        </p>
        <Switch label={t('settings.app_update.auto')} hint={t('settings.app_update.auto_hint')}
            bind:checked={() => status?.auto_update ?? false, (next) => void act('/auto-update', { method: 'PUT', body: JSON.stringify({ enabled: next }) })}
            disabled={busy} data-app-update="auto" />
        {#if status.attached}
            <div class="tm__actions">
                {#if canInstall}
                    <Button variant="confirm" data-app-update="install" disabled={busy}
                        onclick={() => void act('/install', { method: 'POST' })}>{t('settings.app_update.install')}</Button>
                {/if}
                <Button size="sm" data-app-update="check" disabled={busy || working}
                    onclick={() => void act('/check', { method: 'POST' })}>{t('settings.app_update.check')}</Button>
            </div>
        {/if}
    {:else if !problem}
        <p class="tm__sub">{t('settings.app_update.loading')}</p>
    {/if}
    {#if problem}<State kind="error" inline title={problem} />{/if}
</div>
