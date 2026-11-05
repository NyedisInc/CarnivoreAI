
<script lang="ts">
    import type { Snippet } from 'svelte';
    import type { Translate } from '../sessions/types';
    import './cplug-ui.css';

    interface Props {
        name: string;
        unverified?: boolean;
        note?: string | null;
        bar?: boolean;
        fill?: boolean;
        t: Translate;
        children?: Snippet;
    }

    const { name, unverified = false, note = null, bar = true, fill = false, t, children }: Props = $props();
</script>

<section class="cu-frame" class:cu-frame--fill={fill} data-cplug-frame>
    {#if bar}
    <header class="cu-frame__bar">
        <span class="cu-frame__name" data-cplug-name>{name}</span>
        <span class="cu-frame__mark" data-cplug-mark data-unverified={unverified ? '' : undefined}>{t(unverified ? 'cplug_ui.mark.unverified' : 'cplug_ui.mark.third_party')}</span>
    </header>
    {/if}
    {#if note}<p class="cu-frame__note" role="status" data-cplug-note>{note}</p>{/if}
    {#if children}<div class="cu-box" data-cplug-box>{@render children()}</div>{/if}
</section>
