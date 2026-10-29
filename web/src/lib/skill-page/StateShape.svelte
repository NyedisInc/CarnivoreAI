
<script lang="ts">
    interface Props {
        name: 'on' | 'name-only' | 'user-invocable-only' | 'off' | 'flagged' | 'caution';
        size?: number;
    }

    const { name, size = 12 }: Props = $props();
</script>

<svg class="skp-shape" width={size} height={size} viewBox="0 0 14 14" aria-hidden="true" data-shape={name}>
    {#if name === 'on'}
        <rect x="2" y="2" width="10" height="10" fill="currentColor" />
    {:else if name === 'name-only'}
        <rect x="2.5" y="2.5" width="9" height="9" fill="none" stroke="currentColor" />
        <rect x="2" y="2" width="5" height="10" fill="currentColor" />
    {:else if name === 'user-invocable-only'}
        <rect x="2.5" y="2.5" width="9" height="9" fill="none" stroke="currentColor" />
        <circle cx="7" cy="7" r="1.8" fill="currentColor" />
    {:else if name === 'flagged'}
        <path d="M2 2h6.5L12 5.5V12H2Z" fill="currentColor" />
    {:else if name === 'caution'}
        <path d="M2 2h6.5L12 5.5V12H2Z" fill="none" stroke="currentColor" />
    {:else}
        <rect x="2.5" y="2.5" width="9" height="9" fill="none" stroke="currentColor" />
    {/if}
</svg>

<style>
    @layer components {
        .skp-shape {
            display: inline-block;
            flex: none;
            vertical-align: -2px;
        }
    }
</style>
