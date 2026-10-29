
<script lang="ts">
    import { flushSync } from 'svelte';
    import InfoScreen from './InfoScreen.svelte';

    let page = $state<ReturnType<typeof InfoScreen> | null>(null);

    export function show(): void {
        if (!page) flushSync();
        page?.show();
    }

    export function close(): void {
        page?.close();
    }

    export function isOpen(): boolean {
        return page?.isOpen() ?? false;
    }
</script>

<InfoScreen bind:this={page} view="changelog" />
