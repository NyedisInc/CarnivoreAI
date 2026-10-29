
<script lang="ts">
    import type { Snippet } from 'svelte';

    interface Props {
        name: string;
        checked: boolean;
        desc?: string;
        inUse?: string;
        ariaLabel?: string;
        onSelect: () => void;
        children?: Snippet;
    }

    const { name, checked, desc = '', inUse = '', ariaLabel, onSelect, children }: Props = $props();
</script>

<button type="button" class="oc-choice" role="radio" aria-checked={checked} aria-label={ariaLabel} onclick={onSelect}>
    <span class="oc-choice__top">
        <span class="oc-radio" aria-hidden="true"></span>
        <span class="oc-choice__name">{name}</span>
        {#if checked && inUse}<span class="oc-choice__use">{inUse}</span>{/if}
    </span>
    {#if desc}<span class="oc-choice__desc">{desc}</span>{/if}
    {#if children}{@render children()}{/if}
</button>
