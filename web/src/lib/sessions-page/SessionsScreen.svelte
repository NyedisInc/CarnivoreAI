
<script lang="ts">
    import { flushSync } from 'svelte';
    import SessionsPage from '../sessions-page/SessionsPage.svelte';

    let page = $state<ReturnType<typeof SessionsPage> | null>(null);

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

<SessionsPage bind:this={page} />
