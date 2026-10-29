<!-- padding -->
<script lang="ts">
    import Switch from '../../lib/base/Switch.svelte';

    interface Props {
        label: string;
        checked: boolean;
        role?: 'checkbox' | 'switch';
        disabled?: boolean;
        bare?: boolean;
        note?: string;
        hint?: string;
        glyph?: string;
        ariaLabel?: string;
        id?: string;
        [attribute: `data-${string}`]: string | undefined;
        onToggle: (next: boolean) => void;
    }

    const { label, checked, role = 'checkbox', disabled = false, bare = false, note = '', hint = '', glyph = '', ariaLabel, id, onToggle, ...rest }: Props = $props();
</script>

<Switch
    {...rest}
    {label}
    {role}
    {disabled}
    {bare}
    {note}
    {hint}
    {glyph}
    {id}
    aria-label={ariaLabel}
    bind:checked={() => checked, (next) => onToggle(next)}
/>
