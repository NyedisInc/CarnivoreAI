<!--
  Field: a labelled text input or textarea (`.oc-form-field`, field.css); the input itself is the base field
  (`data-field`, elements.css), so it carries no class. Plain markup,
  no library. The label is a real <label for>; help and error lines are tied to the input by aria-describedby, and an
  error sets aria-invalid so the boundary turns coral.
  Inputs: label (string; absent draws the bare input (or, with `multiline`, the bare textarea) for a row or a popup, then pass `aria-label`, like Select), value (string, bindable), multiline (boolean), rows (number, textarea only), placeholder,
    help (string), error (string), id (string, generated when absent), any other input attribute (maxlength, name,
    required, disabled, oninput...). Output: the field column.
  `block` (boolean): the search frame or the bare input fills its container's width (a filter above a list); a labelled column already does.
  Example: <Field label={t('cplug.huddle.ask.other')} bind:value={other} placeholder={t('cplug.huddle.ask.other_placeholder')} />

  THE SEARCH VARIANT (`variant="search"`, sidebar search redesign D): one framed box (`.oc-search`, search-field.css) holding a
  leading search icon, the base input, a clear x drawn WHENEVER there is text (focused or not) with no hover tile, an optional
  key hint (`hint` while empty, `hintFilled` while holding text), and an optional trailing slot (the drawer's mode button). The
  frame is the `oc-focus-host`, so focus brightens the frame's own border and nothing else. The label becomes the input's
  aria-label (no visible caption). Extra inputs: input (bindable <input>), clearLabel (string, the x's accessible name),
  onclear (called after the x emptied the box), hint, hintFilled (strings), trailing (Snippet).
  Example: <Field variant="search" label={t('drawer.search.label')} bind:value bind:input clearLabel={t('drawer.search.clear')} onclear={refocus} hint="/" hintFilled="esc">
-->
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
    input?: HTMLInputElement | null;
    clearLabel?: string;
    onclear?: () => void;
    hint?: string;
    hintFilled?: string;
    trailing?: Snippet;
  }

  const uid = $props.id();
  let {
    label, value = $bindable(''), multiline = false, rows = 3, help, error, id = `oc-field-${uid}`,
    variant, block = false, input = $bindable(null), clearLabel = '', onclear, hint, hintFilled, trailing, 'aria-describedby': describes, ...rest
  }: Props = $props();

  const helpId = $derived(help ? `${id}-help` : undefined);
  const errorId = $derived(error ? `${id}-error` : undefined);
  const shownHint = $derived(value === '' ? hint : hintFilled);

  function clear(): void {
    value = '';
    input?.focus();
    onclear?.();
  }

  const describedBy = $derived([describes, helpId, errorId].filter(Boolean).join(' ') || undefined);
</script>

{#if variant === 'search'}
  <div class="oc-search oc-focus-host" data-block={block || undefined}>
    <span class="oc-search__icon" aria-hidden="true"><Icon name="search" size={12} /></span>
    <input type="text" {...rest} {id} data-field bind:value bind:this={input} aria-label={label ?? ''} />
    {#if value !== ''}
      <button type="button" class="oc-ibtn oc-ibtn--bare oc-search__clear" aria-label={clearLabel}
        onmousedown={(e) => e.preventDefault()} onclick={clear}><Icon name="close" size={11} /></button>
    {/if}
    {#if shownHint}<kbd class="oc-search__hint" aria-hidden="true">{shownHint}</kbd>{/if}
    {#if trailing}<span class="oc-search__trail">{@render trailing()}</span>{/if}
  </div>
{:else if !label}
  {#if multiline}
    <textarea {...rest as Record<string, unknown>} {id} {rows} data-field data-block={block || undefined} bind:value
      aria-describedby={describedBy} aria-invalid={error ? 'true' : undefined}></textarea>
  {:else}
    <input type="text" {...rest as Record<string, unknown>} {id} data-field data-block={block || undefined} bind:value aria-describedby={describedBy} aria-invalid={error ? 'true' : undefined} />
  {/if}
{:else}
<div class="oc-form-field">
  <label class="oc-form-field__label oc-label" for={id}>{label}</label>
  {#if multiline}
    <textarea {...rest as Record<string, unknown>} {id} {rows} data-field bind:value
      aria-describedby={describedBy} aria-invalid={error ? 'true' : undefined}></textarea>
  {:else}
    <input type="text" {...rest} {id} data-field bind:value
      aria-describedby={describedBy} aria-invalid={error ? 'true' : undefined} />
  {/if}
  {#if help}<span class="oc-form-field__help" id={helpId}>{help}</span>{/if}
  {#if error}<span class="oc-form-field__error" id={errorId} role="alert">{error}</span>{/if}
</div>
{/if}
