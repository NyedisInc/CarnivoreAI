
<script lang="ts" module>
    export interface FacetOption {
        readonly value: string;
        readonly label: string;
        readonly group?: string;
    }
</script>

<script lang="ts">
    import Icon from './Icon.svelte';

    interface Props {
        label: string;
        value: string;
        options: readonly FacetOption[];
        onChange: (next: string) => void;
        ariaLabel?: string;
        id?: string;
    }

    const { label, value, options, onChange, ariaLabel, id }: Props = $props();

    const optionGroups = $derived(
        options.reduce<{ group: string | undefined; items: FacetOption[] }[]>((runs, option) => {
            const last = runs[runs.length - 1];
            if (last && last.group === option.group) last.items.push(option);
            else runs.push({ group: option.group, items: [option] });
            return runs;
        }, []),
    );
</script>

<label class="oc-facet oc-focus-host">
    <span class="oc-facet__key">{label}</span>
    <select
        class="oc-facet__select"
        aria-label={ariaLabel ?? label}
        data-facet={id}
        {value}
        onchange={(event) => onChange((event.currentTarget as HTMLSelectElement).value)}
    >
        {#each optionGroups as bucket (bucket.group ?? '')}
            {#if bucket.group}
                <optgroup label={bucket.group}>
                    {#each bucket.items as option (option.value)}
                        <option value={option.value} selected={option.value === value}>{option.label}</option>
                    {/each}
                </optgroup>
            {:else}
                {#each bucket.items as option (option.value)}
                    <option value={option.value} selected={option.value === value}>{option.label}</option>
                {/each}
            {/if}
        {/each}
    </select>
    <Icon name="chevron-down" size={12} />
</label>
