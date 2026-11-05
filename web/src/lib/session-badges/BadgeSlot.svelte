
<script lang="ts">
    import type { BadgeSlotPlan } from './slot';
    import { buttonAttrs } from '../base/classes';

    const { plan }: { plan: BadgeSlotPlan | null } = $props();

    function clickTarget(act: (e: MouseEvent) => void) {
        return (node: HTMLElement) => {
            const on = (e: MouseEvent) => { e.stopPropagation(); e.preventDefault(); act(e); };
            node.addEventListener('click', on);
            return () => node.removeEventListener('click', on);
        };
    }
</script>

{#if plan}
    <span class="row-badge-slot" data-badge-slot>
        {#each plan.items as b (b.kind + ':' + b.key)}
            {#if b.activate}
                {@const act = b.activate}
                <button type="button" {...buttonAttrs('quiet', 'sm')} class="row-badge" data-badge-kind={b.kind} data-tone={b.tone} title={b.title} aria-label={b.title} tabindex="-1" {@attach clickTarget(act)}>{#if b.pct !== undefined}<span class="row-badge__fill" style="width: {Math.max(0, Math.min(100, b.pct))}%"></span>{/if}{b.text}</button>
            {:else}
                <span class="row-badge" data-badge-kind={b.kind} data-tone={b.tone} title={b.title} role="img" aria-label={b.title}>{#if b.pct !== undefined}<span class="row-badge__fill" style="width: {Math.max(0, Math.min(100, b.pct))}%"></span>{/if}{b.text}</span>
            {/if}
        {/each}
        {#if plan.more > 0}
            <span class="row-badge row-badge--more" data-badge-more title={plan.moreTitle} role="img" aria-label={plan.moreTitle}>+{plan.more}</span>
        {/if}
    </span>
{/if}

<style>
    @layer components {
        .row-badge-slot {
            display: inline-flex;
            align-items: center;
            gap: var(--oc-space-0-5);
            flex: 0 1 auto;
            min-width: 0;
            max-width: 22ch;
            overflow: hidden;
        }

        .row-badge {
            position: relative;
            display: inline-flex;
            align-items: center;
            flex-shrink: 0;
            font-family: var(--font-mono);
            font-size: var(--oc-fs-micro);
            line-height: 1.4;
            padding: 0 var(--oc-space-1);
            height: auto;
            min-height: 0;
            border-radius: var(--oc-radius-sm);
            letter-spacing: 0.4px;
            color: var(--oc-text-muted);
            background: transparent;
            border: 1px solid var(--oc-line-faint);
            white-space: nowrap;
            overflow: hidden;
        }

        button.row-badge {
            cursor: pointer;
        }

        button.row-badge:hover {
            color: var(--oc-text-bright);
            border-color: var(--oc-line-panel);
        }

        .row-badge[data-tone='good'] {
            color: var(--oc-green);
        }

        .row-badge[data-tone='warn'] {
            color: var(--oc-yellow);
        }

        .row-badge[data-tone='bad'] {
            color: var(--oc-coral);
        }

        .row-badge[data-tone='stripe'] .row-badge__fill {
            background: repeating-linear-gradient(135deg, color-mix(in oklab, currentColor 22%, transparent) 0 3px, transparent 3px 6px);
        }

        .row-badge--more {
            color: var(--oc-text-secondary);
        }

        .row-badge__fill {
            position: absolute;
            inset: 0 auto 0 0;
            background: color-mix(in oklab, currentColor 18%, transparent);
            pointer-events: none;
        }
    }
</style>
