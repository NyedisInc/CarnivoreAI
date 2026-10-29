<!-- <input type="checkbox"> -->
<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { HTMLInputAttributes } from 'svelte/elements';

  interface Props extends Omit<HTMLInputAttributes, 'type' | 'class' | 'children' | 'checked' | 'indeterminate' | 'group'> {
    label?: string;
    hint?: string;
    checked?: boolean;
    indeterminate?: boolean;
    tone?: 'danger';
    children?: Snippet;
  }

  let { label, hint, checked = $bindable(false), indeterminate = $bindable(false), disabled = false, tone, children, ...rest }: Props = $props();
</script>

<label class="oc-pick" data-disabled={disabled || undefined} data-tone={tone}>
  <input {...rest} type="checkbox" class="oc-pick__input" bind:checked bind:indeterminate {disabled} />
  {#if children || label || hint}
    <span class="oc-pick__text">
      {#if children}{@render children()}{:else if label}<span class="oc-pick__label">{label}</span>{/if}
      {#if hint}<span class="oc-pick__hint">{hint}</span>{/if}
    </span>
  {/if}
</label>
