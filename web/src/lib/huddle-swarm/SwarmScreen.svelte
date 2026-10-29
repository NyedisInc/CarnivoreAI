
<script lang="ts">
    import SwarmPage from './SwarmPage.svelte';

    let open = $state(false);
    let opener: HTMLElement | null = null;

    export function show(): void {
        if (open) return;
        const focused = typeof document !== 'undefined' ? document.activeElement : null;
        opener = focused instanceof HTMLElement ? focused : null;
        open = true;
    }

    export function close(): void {
        if (!open) return;
        open = false;
        if (opener && typeof document !== 'undefined' && document.contains(opener)) opener.focus();
        opener = null;
    }

    export function isOpen(): boolean {
        return open;
    }
</script>

{#if open}<SwarmPage {close} />{/if}
