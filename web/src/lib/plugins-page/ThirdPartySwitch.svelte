
<script lang="ts">
    import Check from '../../opscenter/ui/Check.svelte';
    import type { Translate } from '../sessions/types';
    import { loadThirdParty, sandboxLine, saveThirdParty, type ThirdPartyStatus } from './third-party-switch';
    import './plugin-pane.css';

    interface Props {
        t: Translate;
        load?: () => Promise<ThirdPartyStatus>;
        save?: (enabled: boolean) => Promise<ThirdPartyStatus>;
        onStatus?: (status: ThirdPartyStatus) => void;
    }

    const { t, load = () => loadThirdParty(), save = (enabled) => saveThirdParty(enabled), onStatus }: Props = $props();

    let status = $state<ThirdPartyStatus | null>(null);
    let busy = $state(false);
    let failed = $state(false);

    $effect(() => {
        let live = true;
        load().then(
            (next) => { if (live) status = next; },
            () => { if (live) failed = true; },
        );
        return () => { live = false; };
    });

    async function flip(next: boolean): Promise<void> {
        if (busy) return;
        busy = true;
        failed = false;
        try {
            status = await save(next);
        } catch {
            failed = true;
        } finally {
            busy = false;
        }
    }

    $effect(() => {
        if (status) onStatus?.(status);
    });

    const line = $derived(status ? sandboxLine(status) : null);
</script>

{#if status || failed}
<div data-third-party-switch style="display: contents">
    {#if status}
        <Check
            role="switch"
            label={t('plugins.page.third_party.label')}
            checked={status.enabled}
            disabled={busy}
            data-third-party-toggle="1"
            onToggle={(next) => void flip(next)}
        />
        
        {#if status.enabled && line && !status.sandbox?.ok}
            <span class="plp-note" data-third-party-sandbox={status.sandbox ? (status.sandbox.ok ? 'ok' : 'bad') : 'unchecked'}>{t(line.key, { reason: line.reason ?? '' })}</span>
        {/if}
        {#if status.safe_mode.active}<span class="plp-note" data-third-party-safe>{t('plugins.page.third_party.safe_mode')}</span>{/if}
    {/if}
    {#if failed}<span class="plp-note" role="alert" data-third-party-failed>{t('plugins.page.third_party.failed')}</span>{/if}
</div>
{/if}
