
<script lang="ts">
    import ModelMark from './ModelMark.svelte';
    import type { GlyphChip, ModelPlan } from './row-plan';

    let {
        provider,
        model = null,
        leadHtml = '',
        asleep = false,
        size = 'sm',
    }: {
        provider: GlyphChip;
        model?: ModelPlan | null;
        leadHtml?: string;
        asleep?: boolean;
        size?: 'sm' | 'md';
    } = $props();
</script>

<span
    {...provider.attrs}
    class="{provider.attrs.class ?? 'session-sidebar-row-provider'} sb-avatar sb-avatar--{size}"
    class:sb-avatar--merged={!!model}
    class:sb-avatar--asleep={asleep && !model}
    data-avatar-merged={model ? '1' : undefined}
>{#if model}<span class="sb-avatar__face"><ModelMark {model} /></span><span class="sb-avatar__badge" aria-hidden="true">{@html provider.svg}</span>{:else}{@html provider.svg}{/if}{#if leadHtml}{@html leadHtml}{/if}</span>

<style>
    @layer components {
        :global(.sb-avatar) {
            position: relative;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            flex: 0 0 auto;
            border-radius: var(--oc-radius-sm);
            touch-action: none;
        }
        :global(.sb-avatar--sm) {
            width: 20px;
            height: 20px;
        }
        :global(.sb-avatar--md) {
            width: 28px;
            height: 28px;
            border-radius: var(--oc-radius);
        }
        :global(.sb-avatar--asleep) {
            opacity: 0.6;
        }
        :global(.sb-avatar--merged) {
            background: color-mix(in oklab, var(--oc-ground-hover) 85%, var(--oc-ground-card));
        }
        :global(.sb-avatar__face) {
            display: inline-flex;
            align-items: center;
            justify-content: center;
        }
        :global(.sb-avatar--md .sb-avatar__face svg) {
            width: 16px;
            height: 16px;
        }
        :global(.sb-avatar__badge) {
            position: absolute;
            right: -3px;
            bottom: -3px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 12px;
            height: 12px;
            border-radius: var(--oc-radius-circle);
            background: var(--oc-ground-chrome);
            border: var(--oc-border) solid var(--oc-line-panel);
            pointer-events: none;
        }
        :global(.sb-avatar__badge svg) {
            width: 8px;
            height: 8px;
        }
    }
</style>
