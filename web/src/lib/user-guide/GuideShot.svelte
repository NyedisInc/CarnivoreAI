
<script lang="ts">
    import { onDestroy, onMount } from 'svelte';
    import { Button } from '../base';
    import { fetchFeatureMediaBlob } from '../help/feature-media';
    import { t as appT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import { followGuideTarget } from './guide-nav';
    import type { Hotspot } from './guide-parse';

    interface Props {
        feature: string;
        file: string;
        alt: string;
        hotspots: readonly Hotspot[];
        t?: Translate;
    }

    const { feature, file, alt, hotspots, t = appT }: Props = $props();

    let url = $state<string | null>(null);
    let failed = $state(false);
    let active = $state<number | null>(null);
    const tip = $derived(active === null ? undefined : hotspots[active]);

    onMount(() => {
        void fetchFeatureMediaBlob(feature, file).then(
            (blob) => {
                url = URL.createObjectURL(blob);
            },
            () => {
                failed = true;
            },
        );
    });

    onDestroy(() => {
        if (url) URL.revokeObjectURL(url);
    });
</script>

<figure class="shot" data-guide-shot="{feature}/{file}">
    <div class="shot__frame">
        {#if url}
            <img class="shot__img" src={url} {alt} />
            {#each hotspots as mark, i (i)}
                <button
                    type="button"
                    class="shot__mark"
                    data-base-exempt="a numbered hotspot dot pinned on a screenshot, positioned by percent, not a labelled control"
                    data-guide-mark={i + 1}
                    style="left: {mark.x}%; top: {mark.y}%"
                    aria-label="{i + 1}. {mark.title}. {mark.text}"
                    onclick={() => followGuideTarget(mark.target)}
                    onmouseenter={() => (active = i)}
                    onmouseleave={() => (active = null)}
                    onfocus={() => (active = i)}
                    onblur={() => (active = null)}
                >{i + 1}</button>
            {/each}
            {#if tip && active !== null}
                <div
                    class="shot__tip"
                    class:shot__tip--left={tip.x > 55}
                    class:shot__tip--up={tip.y > 60}
                    style="left: {tip.x}%; top: {tip.y}%"
                    role="tooltip"
                    data-guide-tip
                >
                    <strong>{active + 1}. {tip.title}</strong>
                    <span>{tip.text}</span>
                    <em>{t('docs.shot.open')}</em>
                </div>
            {/if}
        {:else if failed}
            <p class="shot__note" data-guide-shot-failed>{t('docs.shot.load_failed')}</p>
        {:else}
            <p class="shot__note">{alt}</p>
        {/if}
    </div>
    {#if hotspots.length > 0}
        <ol class="shot__list" aria-label={t('docs.shot.marks')}>
            {#each hotspots as mark, i (i)}
                <li>
                    <Button variant="row" data-guide-item={i + 1} onclick={() => followGuideTarget(mark.target)}>
                        <span class="shot__num">{i + 1}</span>
                        <span class="shot__words"><strong>{mark.title}</strong> {mark.text}</span>
                    </Button>
                </li>
            {/each}
        </ol>
    {/if}
</figure>

<style>
    .shot {
        max-width: 960px;
        margin: var(--oc-space-3) 0 0;
    }

    .shot__frame {
        position: relative;
        border: var(--oc-border, 1px) solid var(--oc-line-rule);
        background: var(--oc-ground-titlerow);
    }

    .shot__img {
        display: block;
        width: 100%;
        height: auto;
    }

    .shot__note {
        margin: 0;
        padding: var(--oc-space-5) var(--oc-space-3);
        color: var(--oc-text-muted);
        font-size: var(--oc-fs-body, 12px);
    }

    .shot__mark,
    .shot__num {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        box-sizing: border-box;
        width: 22px;
        height: 22px;
        padding: 0;
        border: var(--oc-border, 1px) solid var(--oc-orange);
        border-radius: 2px;
        background: var(--oc-ground-titlerow);
        color: var(--oc-orange);
        font: 600 11px/1 var(--font-mono);
    }

    .shot__mark {
        --_bd: var(--oc-orange);
        position: absolute;
        transform: translate(-50%, -50%);
        cursor: pointer;
    }

    .shot__mark:hover {
        background: var(--oc-orange);
        color: var(--oc-ground-titlerow);
    }

    .shot__tip {
        position: absolute;
        z-index: 2;
        width: max-content;
        max-width: min(260px, 60%);
        margin: var(--oc-space-4) 0 0 calc(var(--oc-space-2) * -1);
        padding: var(--oc-space-1-5) var(--oc-space-2);
        border: var(--oc-border, 1px) solid var(--oc-line-rule);
        background: var(--oc-ground-titlerow);
        color: var(--oc-text-secondary);
        font-size: var(--oc-fs-body, 12px);
        line-height: 1.4;
        pointer-events: none;
    }

    .shot__tip--left {
        margin-left: 0;
        transform: translateX(calc(-100% + 8px));
    }

    .shot__tip--up {
        margin-top: 0;
        transform: translateY(calc(-100% - 16px));
    }

    .shot__tip--left.shot__tip--up {
        transform: translate(calc(-100% + 8px), calc(-100% - 16px));
    }

    .shot__tip strong {
        display: block;
        color: var(--oc-text-primary);
    }

    .shot__tip em {
        display: block;
        margin-top: var(--oc-space-0-5);
        color: var(--oc-cyan);
        font-style: normal;
    }

    .shot__list {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
        gap: var(--oc-space-1-5) var(--oc-space-4);
        margin: var(--oc-space-2) 0 0;
        padding: 0;
        list-style: none;
    }

    .shot__num {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        box-sizing: border-box;
        width: 22px;
        height: 22px;
        padding: 0;
        border: var(--oc-border, 1px) solid var(--oc-orange);
        border-radius: 2px;
        background: var(--oc-ground-titlerow);
        color: var(--oc-orange);
        font: 600 11px/1 var(--font-mono);
    }

    .shot__mark {
        --_bd: var(--oc-orange);
        position: absolute;
        transform: translate(-50%, -50%);
        cursor: pointer;
    }

    .shot__mark:hover {
        background: var(--oc-orange);
        color: var(--oc-ground-titlerow);
    }

    .shot__tip {
        position: absolute;
        z-index: 2;
        width: max-content;
        max-width: min(260px, 60%);
        margin: var(--oc-space-4) 0 0 calc(var(--oc-space-2) * -1);
        padding: var(--oc-space-1-5) var(--oc-space-2);
        border: var(--oc-border, 1px) solid var(--oc-line-rule);
        background: var(--oc-ground-titlerow);
        color: var(--oc-text-secondary);
        font-size: var(--oc-fs-body, 12px);
        line-height: 1.4;
        pointer-events: none;
    }

    .shot__tip--left {
        margin-left: 0;
        transform: translateX(calc(-100% + 8px));
    }

    .shot__tip--up {
        margin-top: 0;
        transform: translateY(calc(-100% - 16px));
    }

    .shot__tip--left.shot__tip--up {
        transform: translate(calc(-100% + 8px), calc(-100% - 16px));
    }

    .shot__tip strong {
        display: block;
        color: var(--oc-text-primary);
    }

    .shot__tip em {
        display: block;
        margin-top: var(--oc-space-0-5);
        color: var(--oc-cyan);
        font-style: normal;
    }

    .shot__list {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
        gap: var(--oc-space-1-5) var(--oc-space-4);
        margin: var(--oc-space-2) 0 0;
        padding: 0;
        list-style: none;
    }

    .shot__item {
        display: flex;
        align-items: flex-start;
        gap: var(--oc-space-2);
        width: 100%;
        padding: 0;
        border: 0;
        background: none;
        color: var(--oc-text-secondary);
        font: inherit;
        font-size: var(--oc-fs-body, 12px);
        line-height: 1.4;
        text-align: left;
        cursor: pointer;
    }

    .shot__num {
        flex: none;
    }

    .shot__words strong {
        color: var(--oc-text-primary);
    }
</style>
