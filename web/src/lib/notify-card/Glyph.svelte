
<script lang="ts">
    let { name }: { name: 'finished' | 'play' | 'file' | 'image' } = $props();
</script>

<svg viewBox="0 0 24 24" aria-hidden="true">
    {#if name === 'finished'}
        <circle cx="12" cy="12" r="9" /><path d="M8 12.5l3 3 5-6" />
    {:else if name === 'play'}
        <path d="M7 5l12 7-12 7z" fill="currentColor" />
    {:else if name === 'file'}
        <path d="M6 3h8l4 4v14H6z" /><path d="M14 3v4h4M9 13h6M9 17h6" />
    {:else}
        <rect x="3" y="5" width="18" height="14" rx="1.5" /><circle cx="9" cy="10" r="1.6" /><path d="M4 18l5-5 4 4 3-3 4 4" />
    {/if}
</svg>
