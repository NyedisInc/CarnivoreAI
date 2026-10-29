
<script lang="ts">
    import type { Snippet } from 'svelte';

    interface Props {
        id: string;
        label: string;
        children: Snippet;
    }

    const { id, label, children }: Props = $props();
</script>

<div class="filter-group" data-group={id} role="group" aria-label={label}>
    <span class="filter-group__label">{label}</span>
    {@render children()}
</div>

<style>
    .filter-group {
        display: inline-flex;
        align-items: stretch;
        flex: none;
        box-sizing: border-box;
        height: var(--oc-rowheight, 26px);
        min-width: 0;
        border: 1px solid var(--oc-line-panel);
        border-radius: 2px;
    }

    .filter-group:focus-within {
        border-color: var(--oc-line-rule);
    }

    .filter-group__label {
        display: flex;
        align-items: center;
        padding: 0 8px;
        border-radius: 1px 0 0 1px;
        background: var(--oc-ground-titlerow);
        box-shadow: inset -1px 0 0 0 var(--oc-line-panel);
        color: var(--oc-text-muted);
        font-size: 10px;
        letter-spacing: 0.6px;
        text-transform: uppercase;
        white-space: nowrap;
    }

    .filter-group :global(.oc-seg) {
        border: 0;
        border-radius: 0;
        height: 100%;
    }

    .filter-group :global(.oc-seg__item) {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 0 10px;
        color: var(--oc-text-secondary);
        font-size: 11px;
    }

    .filter-group :global(.oc-seg__item[data-kind]) {
        gap: 3px;
        padding: 0 5px 0 2px;
    }

    .filter-group :global(.oc-seg__item:hover:not(:disabled)) {
        background: var(--oc-ground-hover);
        color: var(--oc-text-primary);
    }

    .filter-group :global(.oc-seg__item[aria-checked='true']) {
        background: var(--oc-orange-tint);
        color: var(--oc-text-bright);
    }

    @media (max-width: 767px) {
        .filter-group {
            height: 44px;
        }

        .filter-group :global(.oc-seg__item) {
            min-width: 44px;
            justify-content: center;
        }
    }
</style>
