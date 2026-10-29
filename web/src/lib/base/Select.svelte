
<script lang="ts" module>
  export interface SelectOption {
    value: string;
    label: string;
    disabled?: boolean;
  }

  export interface SelectGroup {
    group: string;
    options: readonly SelectOption[];
  }

  export type SelectChoice = SelectOption | SelectGroup;

  export function isGroup(choice: SelectChoice): choice is SelectGroup {
    return 'group' in choice;
  }
</script>

<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { HTMLSelectAttributes } from 'svelte/elements';

  interface Props extends Omit<HTMLSelectAttributes, 'value' | 'class' | 'children' | 'size'> {
    value?: string;
    options?: readonly SelectChoice[];
    children?: Snippet;
    size?: 'md' | 'sm';
    label?: string;
    help?: string;
    error?: string;
  }

  const uid = $props.id();
  let { value = $bindable(''), options, children, size = 'md', label, help, error, id = `oc-select-${uid}`, ...rest }: Props = $props();

  const helpId = $derived(help ? `${id}-help` : undefined);
  const errorId = $derived(error ? `${id}-error` : undefined);
  const describedBy = $derived([helpId, errorId].filter(Boolean).join(' ') || undefined);
</script>

{#snippet choices()}
  {#if children}
    {@render children()}
  {:else if options}
    {#each options as choice (isGroup(choice) ? `g:${choice.group}` : choice.value)}
      {#if isGroup(choice)}
        <optgroup label={choice.group}>
          {#each choice.options as option (option.value)}<option value={option.value} disabled={option.disabled}>{option.label}</option>{/each}
        </optgroup>
      {:else}
        <option value={choice.value} disabled={choice.disabled}>{choice.label}</option>
      {/if}
    {/each}
  {/if}
{/snippet}

{#if label}
  <div class="oc-form-field">
    <label class="oc-form-field__label oc-label" for={id}>{label}</label>
    <select {...rest} {id} data-field data-size={size === 'sm' ? 'sm' : undefined} bind:value
      aria-describedby={describedBy} aria-invalid={error ? 'true' : undefined}>{@render choices()}</select>
    {#if help}<span class="oc-form-field__help" id={helpId}>{help}</span>{/if}
    {#if error}<span class="oc-form-field__error" id={errorId} role="alert">{error}</span>{/if}
  </div>
{:else}
  <select {...rest} {id} data-field data-size={size === 'sm' ? 'sm' : undefined} bind:value
    aria-invalid={error ? 'true' : undefined}>{@render choices()}</select>
{/if}
