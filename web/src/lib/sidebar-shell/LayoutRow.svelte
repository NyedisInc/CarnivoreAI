
<script lang="ts">
    import RowChip from './RowChip.svelte';
    import RowMenuTrigger from './RowMenuTrigger.svelte';
    import RowPin from './RowPin.svelte';
    import type { LayoutRowPlan } from './row-plan';

    let { p }: { p: LayoutRowPlan } = $props();
    const parts = $derived(p.parts);
</script>

<div {...parts.attrs}><div class="session-sidebar-row-main">{#if parts.lightHtml}{@html parts.lightHtml}{/if}{#if parts.toggle}<RowChip chip={parts.toggle} />{/if}{#if parts.icon}<RowChip chip={parts.icon} />{/if}<RowChip chip={{ attrs: parts.name.attrs }}>{#if p.nameMatch}{p.nameMatch.before}<mark class="sd-mark">{p.nameMatch.match}</mark>{p.nameMatch.after}{:else}{parts.name.text}{/if}{#if parts.name.fxHtml}{@html parts.name.fxHtml}{/if}</RowChip><RowChip chip={{ attrs: { class: 'session-sidebar-row-subtitle' }, text: parts.subtitle }} /><RowPin attrs={p.pin} />{#if p.menu}<RowMenuTrigger spec={p.menu} />{/if}</div></div>
