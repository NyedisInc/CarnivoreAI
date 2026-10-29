
<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { HTMLInputAttributes } from 'svelte/elements';
  import Icon from '../../opscenter/ui/Icon.svelte';

  interface Props extends Omit<HTMLInputAttributes, 'value' | 'class'> {
    label?: string;
    value?: string;
    multiline?: boolean;
    rows?: number;
    help?: string;
    error?: string;
    block?: boolean;
    variant?: 'search';
    element?: HTMLInputElement | HTMLTextAreaElement | null;
    input?: HTMLInputElement | null;
    clearLabel?: string;
    onclear?: () => void;
    hint?: string;
    hintFilled?: string;
    lead?: Snippet;
    trailing?: Snippet;
  }

  const uid = $props.id();
  let {
    label, value = $bindable(''), multiline = false, rows = 3, help, error, id = `oc-field-${uid}`,
    variant, block = false, element = $bindable(null), input = $bindable(null), clearLabel = '', onclear, hint, hintFilled, lead, trailing, 'aria-describedby': describes, ...rest
  }: Props = $props();

  const helpId = $derived(help ? `${id}-help` : undefined);
  const errorId = $derived(error ? `${id}-error` : undefined);
  const shownHint = $derived(value === '' ? hint : hintFilled);

  function clear(): void {
    value = '';
    element?.focus();
    onclear?.();
  }

  $effect(() => {
    if (variant === 'search') input = element instanceof HTMLInputElement ? element : null;
  });

  const describedBy = $derived([describes, helpId, errorId].filter(Boolean).join(' ') || undefined);
</script>

{#if variant === 'search'}
  <div class="oc-search oc-focus-host" data-block={block || undefined}>
    <span class="oc-search__icon" aria-hidden="true"><Icon name="search" size={12} /></span>
    {#if lead}<span class="oc-search__lead">{@render lead()}</span>{/if}
    <input type="text" {...rest} {id} data-field bind:value bind:this={element} aria-label={label ?? ''} />
    {#if value !== ''}
      <button type="button" class="oc-ibtn oc-ibtn--bare oc-search__clear" aria-label={clearLabel}
        onmousedown={(e) => e.preventDefault()} onclick={clear}><Icon name="close" size={11} /></button>
    {/if}
    {#if shownHint}<kbd class="oc-search__hint" aria-hidden="true">{shownHint}</kbd>{/if}
    {#if trailing}<span class="oc-search__trail">{@render trailing()}</span>{/if}
  </div>
{:else if !label}
  {#if multiline}
    <textarea {...rest as Record<string, unknown>} {id} {rows} data-field data-block={block || undefined} bind:value bind:this={element}
      aria-describedby={describedBy} aria-invalid={error ? 'true' : undefined}></textarea>
  {:else}
    <input type="text" {...rest as Record<string, unknown>} {id} data-field data-block={block || undefined} bind:value bind:this={element} aria-describedby={describedBy} aria-invalid={error ? 'true' : undefined} />
  {/if}
{:else}
<div class="oc-form-field">
  <label class="oc-form-field__label oc-label" for={id}>{label}</label>
  {#if multiline}
    <textarea {...rest as Record<string, unknown>} {id} {rows} data-field bind:value bind:this={element}
      aria-describedby={describedBy} aria-invalid={error ? 'true' : undefined}></textarea>
  {:else}
    <input type="text" {...rest} {id} data-field bind:value bind:this={element}
      aria-describedby={describedBy} aria-invalid={error ? 'true' : undefined} />
  {/if}
  {#if help}<span class="oc-form-field__help" id={helpId}>{help}</span>{/if}
  {#if error}<span class="oc-form-field__error" id={errorId} role="alert">{error}</span>{/if}
</div>
{/if}
