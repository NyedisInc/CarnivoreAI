
<script lang="ts">
    interface Props {
        value: string;
        onInput: (next: string) => void;
        label?: string;
        placeholder?: string;
        ariaLabel?: string;
        keyshortcuts?: string;
        input?: HTMLInputElement | undefined;
        onkeydown?: (event: KeyboardEvent) => void;
        [attribute: `data-${string}`]: string | undefined;
    }

    let { value, onInput, label, placeholder, ariaLabel, keyshortcuts, input = $bindable(), onkeydown, ...rest }: Props = $props();
</script>

<label class="oc-page__search">
    {#if label}<span class="oc-label">{label}</span>{/if}
    <input
        bind:this={input}
        class="oc-field"
        type="search"
        autocomplete="off"
        spellcheck="false"
        {placeholder}
        aria-label={ariaLabel ?? (label ? undefined : placeholder)}
        aria-keyshortcuts={keyshortcuts}
        {value}
        {onkeydown}
        {...rest}
        oninput={(event) => onInput((event.currentTarget as HTMLInputElement).value)}
    />
</label>
