
<script lang="ts">
    import NotifyCard from '../../notify-card/NotifyCard.svelte';
    import type { NotifyKind } from '../../notify-card/contract.gen';
    import type { Sample } from './logic';

    interface Props { sample: Sample | null; kind: NotifyKind; iphone: boolean; computer: boolean; level: string }
    const { sample, kind, iphone, computer, level }: Props = $props();
</script>

{#snippet banner(showLevel: boolean)}
    {#if sample}
        <div class="pv-note" data-ins="banner">
            <span class="pv-pic" aria-hidden="true">C</span>
            <span class="pv-text">
                <span class="pv-title">{sample.title}</span>
                <span>{sample.sub}</span>
                <span class="pv-body">{sample.body}</span>
                {#if showLevel && sample.lv === 't'}<span class="pv-level">{level}</span>{/if}
            </span>
            <span class="pv-ts">{sample.card.ts}</span>
        </div>
    {/if}
{/snippet}

{#if iphone}
    <div class="pv-wall" data-ins="wall-banner"><div class="pv-sheet">{@render banner(true)}</div></div>
    <div class="pv-wall" data-ins="wall-card">
        <div class="pv-sheet pv-sheet--card"><NotifyCard card={sample?.card ?? null} {kind} body={sample?.body} typing={false} /></div>
    </div>
{/if}
{#if computer}
    <div class="pv-wall" data-ins="wall-computer"><div class="pv-sheet">{@render banner(false)}</div></div>
{/if}
