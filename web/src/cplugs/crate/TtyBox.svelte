
<script lang="ts">
    import type { Snippet } from 'svelte';
    import './crate-dialog.css';

    interface Props {
        label: string;
        fit?: boolean;
        bar?: Snippet;
        children: Snippet;
    }
    const { label, fit = false, bar, children }: Props = $props();
</script>

<div class="crt-tty" data-crt-tty>
    <div class="crt-tty__bar">
        <span class="crt-tty__label">{label}</span>
        {#if bar}<span class="crt-tty__state">{@render bar()}</span>{/if}
    </div>
    <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
    <div class={fit ? 'crt-tty__screen crt-tty__screen--fit' : 'crt-tty__screen'} role="region" aria-label={label} tabindex="0">
        {@render children()}
    </div>
</div>
