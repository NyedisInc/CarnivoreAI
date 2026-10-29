
<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { HTMLInputAttributes } from 'svelte/elements';
  import { useRadioGroup } from './radio-context';

  interface Props extends Omit<HTMLInputAttributes, 'type' | 'class' | 'children' | 'checked' | 'group' | 'value'> {
    value: string;
    label?: string;
    hint?: string;
    checked?: boolean;
    children?: Snippet;
  }

  let { value, label, hint, checked = $bindable(false), disabled = false, name, children, onchange, ...rest }: Props = $props();

  const group = useRadioGroup();
  const off = $derived(disabled || (group?.disabled ?? false));
</script>

<label class="oc-pick" data-disabled={off || undefined}>
  {#if group}
    <input {...rest} type="radio" class="oc-pick__input" name={group.name} {value} checked={group.value === value}
      disabled={off} onchange={(event) => { group.select(value); onchange?.(event); }} />
  {:else}
    <input {...rest} type="radio" class="oc-pick__input" {name} {value} {checked} disabled={off}
      onchange={(event) => { checked = event.currentTarget.checked; onchange?.(event); }} />
  {/if}
  {#if children || label || hint}
    <span class="oc-pick__text">
      {#if children}{@render children()}{:else if label}<span class="oc-pick__label">{label}</span>{/if}
      {#if hint}<span class="oc-pick__hint">{hint}</span>{/if}
    </span>
  {/if}
</label>
