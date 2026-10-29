
<script lang="ts">
    import type { Snippet } from 'svelte';
    import './panel.css';

    interface Props {
        label: string;
        aux?: string;
        primary?: boolean;
        id?: string;
        class?: string;
        children: Snippet;
    }
    const { label, aux, primary = false, id, class: extra = '', children }: Props = $props();
</script>

<section class="d-panel {extra}" {id}>
    <header class="d-panel__bar" class:d-panel__bar--primary={primary}>
        <h3 class="pl-label d-panel__lab">{label}</h3>
        {#if aux}<span class="d-panel__aux">{aux}</span>{/if}
    </header>
    <div class="d-panel__body">{@render children()}</div>
</section>
