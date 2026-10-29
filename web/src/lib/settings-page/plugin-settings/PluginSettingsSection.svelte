
<script lang="ts">
    import { tick } from 'svelte';
    import '../../plugins-page/plugin-pane.css';
    import Card from '../../base/Card.svelte';
    import PluginSettings from '../../plugins-page/PluginSettings.svelte';
    import type { Translate } from '../../sessions/types';
    import type { PluginEntry } from './plugin-entries';

    interface Props {
        entry: PluginEntry;
        t: Translate;
        anchor?: string | null;
        onSaved?: () => void;
    }

    const { entry, t, anchor = null, onSaved }: Props = $props();
    let root = $state<HTMLElement | undefined>();

    $effect(() => {
        const key = anchor;
        const host = root;
        if (!key || !host) return;
        void tick().then(() => {
            const row = Array.from(host.querySelectorAll<HTMLElement>('[data-setting]')).find((el) => el.dataset.setting === key);
            row?.scrollIntoView?.({ block: 'center' });
            row?.querySelector<HTMLElement>('input, select, textarea, button')?.focus({ preventScroll: true });
        });
    });
</script>

<div class="oc-page__scroll st-panel" data-plugin-entry={entry.id} bind:this={root}>
    <div class="oc-page__main st-main">
        <div class="st-group">
            {#if entry.item.brief}<p class="st-tabhint">{entry.item.brief}</p>{/if}
            <Card title={entry.name} data-st-frame>
                {#key entry.id}
                    <PluginSettings plugin={entry.item} {t} onSaved={() => onSaved?.()} />
                {/key}
            </Card>
        </div>
    </div>
</div>

<style>
    [data-plugin-entry] :global(.plp-region) {
        padding: 0;
    }
</style>
