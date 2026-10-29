
<script lang="ts">
    import Button from '../base/Button.svelte';
    import HelpFeatures from '../help/HelpFeatures.svelte';
    import { renderTree } from '../../opscenter/cells/notes/markdown';
    import { t as appT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import { followGuideTarget } from './guide-nav';
    import { guideLinkAllowed, type GuideBlock } from './guide-parse';
    import GuideShot from './GuideShot.svelte';
    import McpToolList from './McpToolList.svelte';
    import LightsLegend from './LightsLegend.svelte';
    import { openSidebarLegend } from './sidebar-legend';

    interface Props {
        blocks: readonly GuideBlock[];
        t?: Translate;
    }

    const { blocks, t = appT }: Props = $props();

    function paint(node: HTMLElement, md: Extract<GuideBlock, { kind: 'md' }>): void {
        node.replaceChildren(renderTree(md.blocks, node.ownerDocument, guideLinkAllowed));
    }

    function follow(event: MouseEvent): void {
        const link = (event.target as Element | null)?.closest?.('a');
        const href = link?.getAttribute('href') ?? '';
        if (!link || !href.startsWith('#')) return;
        event.preventDefault();
        followGuideTarget(href);
    }
</script>

{#each blocks as block, i (i)}
    {#if block.kind === 'md'}
        <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
        <div class="guide-md" use:paint={block} onclick={follow}></div>
    {:else if block.kind === 'shot'}
        <GuideShot feature={block.feature} file={block.file} alt={block.alt} hotspots={block.hotspots} {t} />
    {:else if block.kind === 'legend'}
        <LightsLegend rows={block.rows} />
    {:else if block.kind === 'component' && block.name === 'feature-index'}
        <HelpFeatures />
    {:else if block.kind === 'component' && block.name === 'mcp-tools'}
        <McpToolList {t} />
    {:else if block.kind === 'component' && block.name === 'open-legend'}
        <p class="guide-md"><Button variant="quiet" size="sm" data-docs-marks-open="" onclick={openSidebarLegend}>{t('docs.marks.open')}</Button></p>
    {/if}
{/each}

<style>
    .guide-md {
        max-width: 78ch;
        color: var(--oc-text-secondary);
        font-size: var(--oc-fs-body, 12px);
        line-height: 1.5;
    }

    .guide-md :global(p),
    .guide-md :global(ol),
    .guide-md :global(ul) {
        margin: var(--oc-space-2) 0 0;
    }

    .guide-md :global(ol),
    .guide-md :global(ul) {
        padding-left: calc(var(--oc-space-4) + var(--oc-space-1));
    }

    .guide-md :global(li + li) {
        margin-top: var(--oc-space-1-5);
    }

    .guide-md :global(h2),
    .guide-md :global(h3),
    .guide-md :global(h4) {
        margin: calc(var(--oc-space-3) + var(--oc-space-0-5)) 0 0;
        color: var(--oc-text-primary);
        font-size: var(--oc-fs-body, 12px);
        font-weight: 600;
    }

    .guide-md :global(a) {
        color: var(--oc-cyan);
    }

    .guide-md :global(code) {
        font-family: var(--font-mono);
        color: var(--oc-text-primary);
    }

    .guide-md :global(pre) {
        margin: var(--oc-space-2) 0 0;
        padding: var(--oc-space-2) calc(var(--oc-space-2) + var(--oc-space-0-5));
        overflow-x: auto;
        border: var(--oc-border, 1px) solid var(--oc-line-rule);
        font-family: var(--font-mono);
        line-height: 1.45;
        color: var(--oc-text-primary);
    }
</style>
