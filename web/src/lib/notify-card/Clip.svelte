
<script lang="ts">
    import type { Snippet } from 'svelte';
    import { t } from '../i18n/index.svelte';
    import { LIMITS } from './contract.gen';

    let { count = 0, unit = 'lines', children }: { count?: number; unit?: 'lines' | 'files'; children: Snippet } = $props();

    let box: HTMLElement | undefined = $state();
    let measured = $state(false);
    const clipped = $derived(count > LIMITS.card_clip_lines || measured);

    $effect(() => {
        if (box) measured = box.scrollHeight > box.clientHeight + 1;
    });
</script>

<div class="nc-clip" bind:this={box} data-clipped={clipped ? '' : undefined} style:--lines={LIMITS.card_clip_lines}>{@render children()}</div>
{#if clipped}
    <div class="nc-more">
        {count > LIMITS.card_clip_lines ? t('notify.card.state.more_count', { count, unit: t('notify.card.unit.' + unit) }) : t('notify.card.state.more')}
    </div>
{/if}
