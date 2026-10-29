
<script lang="ts">
    let open = $state(false);

    export function show(): void {
        open = true;
    }

    export function close(): void {
        open = false;
    }

    export function isOpen(): boolean {
        return open;
    }
</script>

{#if open}
    <div class="fixture-page">open</div>
{/if}
