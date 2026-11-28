
<script lang="ts">
    import Button from '../base/Button.svelte';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import { t } from '../i18n/index.svelte';
    import { isSleepFoldOpen, toggleSleepFoldBand } from '../drawer/sleep-fold.svelte';
    import SidebarRow from './SidebarRow.svelte';
    import type { RowPlan } from './row-plan';

    let { bandKey, rows }: { bandKey: string; rows: RowPlan[] } = $props();

    const open = $derived(isSleepFoldOpen(bandKey));
</script>

{#if rows.length}
    <div class="sb-sleep-fold" data-sleep-fold={bandKey} data-open={open ? '1' : '0'}>
        <Button
            variant="quiet"
            size="sm"
            data-sleep-fold-toggle={bandKey}
            aria-expanded={open}
            aria-label={t('sidebar.sleep_fold.toggle', { count: rows.length })}
            onclick={() => toggleSleepFoldBand(bandKey)}
        >
            <span class="sb-sleep-fold__moon" aria-hidden="true"><Icon name="moon" size={12} /></span>
            <span class="sb-sleep-fold__count">{t('sidebar.sleep_fold.count', { count: rows.length })}</span>
            <span class="sb-sleep-fold__chev" class:sb-sleep-fold__chev--open={open} aria-hidden="true"><Icon name="chevron-right" size={12} /></span>
        </Button>
        {#if open}
            {#each rows as r (r.key)}<SidebarRow {r} />{/each}
        {/if}
    </div>
{/if}

<style>
    @layer components {
        .sb-sleep-fold {
            display: flex;
            flex-direction: column;
            row-gap: var(--sidebar-row-gap);
            min-width: 0;
        }
        .sb-sleep-fold > :global([data-sleep-fold-toggle]) {
            display: flex;
            align-items: center;
            justify-content: flex-start;
            gap: var(--oc-space-1-5);
            width: 100%;
            min-width: 0;
            height: 26px;
            min-height: 26px;
            padding: 0 var(--oc-space-2);
            border: 0;
            border-radius: var(--oc-radius);
            background: transparent;
            color: color-mix(in oklab, var(--oc-text-dim) 55%, var(--oc-ground-chrome));
            font-size: var(--oc-fs-micro);
            text-align: left;
            text-transform: none;
            letter-spacing: normal;
        }
        .sb-sleep-fold > :global([data-sleep-fold-toggle]:hover) {
            background: var(--oc-ground-hover);
            color: var(--oc-text-secondary);
        }
        .sb-sleep-fold__moon {
            display: inline-flex;
            flex: 0 0 auto;
            color: inherit;
        }
        .sb-sleep-fold__count {
            flex: 0 0 auto;
            white-space: nowrap;
            font-variant-numeric: tabular-nums;
        }
        .sb-sleep-fold__chev {
            display: inline-flex;
            flex: 0 0 auto;
            margin-left: auto;
            transition: transform var(--oc-motion-fast) ease;
        }
        .sb-sleep-fold__chev--open {
            transform: rotate(90deg);
        }
        @media (prefers-reduced-motion: reduce) {
            .sb-sleep-fold__chev {
                transition: none;
            }
        }
    }
</style>
