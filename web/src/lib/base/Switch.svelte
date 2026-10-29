<!-- <button class="oc-check" role="switch" (or "checkbox") aria-checked> padding: a switch inline in a row that already has its frame),
    role ('switch', the default, for a setting; -->
<script lang="ts">
  import type { HTMLButtonAttributes } from 'svelte/elements';
  import Icon from '../../opscenter/ui/Icon.svelte';

  interface Props extends Omit<HTMLButtonAttributes, 'class' | 'children' | 'role' | 'type' | 'aria-checked' | 'onclick' | 'onchange'> {
    label: string;
    checked?: boolean;
    hint?: string;
    note?: string;
    bare?: boolean;
    role?: 'switch' | 'checkbox';
    glyph?: string;
    onchange?: (next: boolean) => void;
  }

  let { label, checked = $bindable(false), hint = '', note = '', bare = false, role = 'switch', glyph = '', disabled = false, onchange, ...rest }: Props = $props();

  function toggle(): void {
    const next = !checked;
    checked = next;
    onchange?.(next);
  }
</script>

<button
  {...rest}
  type="button"
  class="oc-check"
  class:oc-check--bare={bare || !label.trim()}
  {role}
  aria-checked={checked}
  {disabled}
  onclick={toggle}
>
  <span class="oc-check__box" aria-hidden="true"></span>
  {#if glyph}<span class="oc-check__glyph" aria-hidden="true"><Icon name={glyph} size={12} /></span>{/if}
  {#if hint}
    <span class="oc-check__text"><span class="oc-check__label">{label}</span><span class="oc-check__hint">{hint}</span></span>
  {:else}
    <span class="oc-check__label">{label}</span>
  {/if}
  {#if note}<span class="oc-check__note">{note}</span>{/if}
</button>
