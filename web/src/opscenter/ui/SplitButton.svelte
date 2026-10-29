
<script lang="ts" module>
    export interface SplitOption {
        readonly value: string;
        readonly label: string;
    }
</script>

<script lang="ts">
    import Button from '../../lib/base/Button.svelte';
    import type { ButtonVariant } from '../../lib/base/classes';
    import Icon from './Icon.svelte';

    interface Props {
        label: string;
        options: readonly SplitOption[];
        value: string;
        onChange: (next: string) => void;
        onMain: () => void;
        disabled?: boolean;
        variant?: ButtonVariant;
        selectLabel: string;
        title?: string;
        attrs?: Readonly<Record<string, string | number | undefined>>;
    }

    const { label, options, value, onChange, onMain, disabled = false, variant = 'secondary', selectLabel, title, attrs = {} }: Props = $props();
</script>

<span class="oc-split">
    <Button size="sm" {variant} {disabled} {title} onclick={onMain} {...attrs}>{label}</Button>
    <span class="oc-split__caret">
        <Button size="sm" {variant} tabindex={-1} aria-hidden="true"><Icon name="chevron-down" size={12} /></Button>
        <select class="oc-split__select" data-base-exempt="the invisible native picker laid over the caret button, which is the drawn control" aria-label={selectLabel} {value} onchange={(event) => onChange((event.currentTarget as HTMLSelectElement).value)}>
            {#each options as option (option.value)}<option value={option.value} selected={option.value === value}>{option.label}</option>{/each}
        </select>
    </span>
</span>
