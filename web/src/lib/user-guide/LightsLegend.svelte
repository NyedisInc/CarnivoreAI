
<script lang="ts">
    import StatusLed from '../StatusLed.svelte';
    import { STATUS_LABELS } from '../status-dot';
    import type { LegendRow } from './guide-parse';

    interface Props {
        rows: readonly LegendRow[];
    }

    const { rows }: Props = $props();
</script>

<ul class="lights" data-lights>
    {#each rows as row (row.state)}
        <li class="lights__item" data-light-state={row.state}>
            <span class="lights__led"><StatusLed status={row.state} size="14px" /></span>
            <span class="lights__body">
                <span class="lights__name">{STATUS_LABELS[row.state] ?? row.state}</span>
                <span class="lights__hue">{row.hue}</span>
                <span class="lights__text">{row.text}</span>
            </span>
        </li>
    {/each}
</ul>

<style>
    .lights {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
        gap: var(--oc-space-2) var(--oc-space-4);
        margin: var(--oc-space-2) 0 0;
        padding: 0;
        list-style: none;
    }

    .lights__item {
        display: flex;
        align-items: flex-start;
        gap: var(--oc-space-2);
        min-width: 0;
        padding-top: var(--oc-space-1-5);
        box-shadow: 0 -1px 0 var(--oc-line-rule);
    }

    .lights__led {
        flex: none;
        padding-top: calc(var(--oc-space-0-5) / 2);
    }

    .lights__body {
        display: block;
        min-width: 0;
        font-size: var(--oc-fs-body, 12px);
        line-height: 1.4;
    }

    .lights__name {
        color: var(--oc-text-primary);
        font-family: var(--font-mono);
    }

    .lights__hue {
        margin-left: var(--oc-space-1-5);
        color: var(--oc-text-muted);
        font-size: var(--oc-fs-label);
        letter-spacing: 0.08em;
        text-transform: uppercase;
    }

    .lights__text {
        display: block;
        margin-top: var(--oc-space-0-5);
        color: var(--oc-text-secondary);
    }
</style>
