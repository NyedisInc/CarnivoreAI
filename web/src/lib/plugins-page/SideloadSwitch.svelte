
<script lang="ts">
    import Check from '../../opscenter/ui/Check.svelte';
    import type { Translate } from '../sessions/types';
    import { loadSideload, saveSideload, type SideloadStatus } from './sideload-switch';
    import './plugin-pane.css';

    interface Props {
        t: Translate;
        load?: () => Promise<SideloadStatus>;
        save?: (enabled: boolean) => Promise<SideloadStatus>;
    }

    const { t, load = () => loadSideload(), save = (enabled) => saveSideload(enabled) }: Props = $props();

    let status = $state<SideloadStatus | null>(null);
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

</script>

{#if status || failed}
<div data-sideload-switch style="display: contents">
    {#if status}
        <Check
            role="switch"
            label={t('plugins.page.sideload.label')}
            checked={status.enabled}
            disabled={busy}
            data-sideload-toggle="1"
            onToggle={(next) => void flip(next)}
        />
        {#if status.enabled}
            <span class="plp-note" data-sideload-count>{t('plugins.page.sideload.count', { count: status.items.length })}</span>
        {/if}
    {/if}
    {#if failed}<span class="plp-note" role="alert" data-sideload-failed>{t('plugins.page.sideload.failed')}</span>{/if}
</div>
{/if}
