<!-- <input type="number" data-field> -->
<script lang="ts">
  import type { HTMLInputAttributes } from 'svelte/elements';
  import { t } from '../i18n/index.svelte';
  import IconButton from './IconButton.svelte';

  interface Props extends Omit<HTMLInputAttributes, 'value' | 'class' | 'type' | 'min' | 'max' | 'step' | 'size' | 'onchange'> {
    value?: number | null;
    min?: number;
    max?: number;
    step?: number;
    stepper?: boolean;
    size?: 'md' | 'sm';
    label?: string;
    help?: string;
    error?: string;
    decreaseLabel?: string;
    increaseLabel?: string;
    onchange?: (value: number | null) => void;
  }

  const uid = $props.id();
  let {
    value = $bindable(null), min, max, step = 1, stepper = false, size = 'md', label, help, error, decreaseLabel, increaseLabel,
    id = `oc-number-${uid}`, disabled = false, onchange, onkeydown, ...rest
  }: Props = $props();

  const helpId = $derived(help ? `${id}-help` : undefined);
  const errorId = $derived(error ? `${id}-error` : undefined);
  const describedBy = $derived([helpId, errorId].filter(Boolean).join(' ') || undefined);
  const atMin = $derived(min !== undefined && value !== null && value <= min);
  const atMax = $derived(max !== undefined && value !== null && value >= max);

  function places(n: number): number {
    return (String(n).split('.')[1] ?? '').length;
  }

  function stepFrom(from: number | null, direction: 1 | -1): number {
    const digits = Math.max(places(step), places(from ?? 0), min === undefined ? 0 : places(min));
    let next = Number(((from ?? 0) + direction * step).toFixed(digits));
    if (min !== undefined) next = Math.max(min, next);
    if (max !== undefined) next = Math.min(max, next);
    return next;
  }

  function nudge(direction: 1 | -1): void {
    if (disabled) return;
    value = stepFrom(value, direction);
    onchange?.(value);
  }

  function key(event: KeyboardEvent & { currentTarget: EventTarget & HTMLInputElement }): void {
    (onkeydown as ((e: KeyboardEvent) => void) | undefined)?.(event);
    if (event.defaultPrevented || (event.key !== 'ArrowUp' && event.key !== 'ArrowDown')) return;
    event.preventDefault();
    nudge(event.key === 'ArrowUp' ? 1 : -1);
  }
</script>

{#snippet row()}
  <div class="oc-number" data-size={size === 'sm' ? 'sm' : undefined}>
    {#if stepper}
      <IconButton label={decreaseLabel ?? t('base.number.decrease')} icon="minus" disabled={disabled || atMin} tabindex={-1} onclick={() => nudge(-1)} />
    {/if}
    <input {...rest} {id} type="number" data-field data-size={size === 'sm' ? 'sm' : undefined} {min} {max} {step} {disabled}
      bind:value onchange={() => onchange?.(value)} onkeydown={key}
      aria-describedby={describedBy} aria-invalid={error ? 'true' : undefined} />
    {#if stepper}
      <IconButton label={increaseLabel ?? t('base.number.increase')} icon="plus" disabled={disabled || atMax} tabindex={-1} onclick={() => nudge(1)} />
    {/if}
  </div>
{/snippet}

{#if label}
  <div class="oc-form-field">
    <label class="oc-form-field__label oc-label" for={id}>{label}</label>
    {@render row()}
    {#if help}<span class="oc-form-field__help" id={helpId}>{help}</span>{/if}
    {#if error}<span class="oc-form-field__error" id={errorId} role="alert">{error}</span>{/if}
  </div>
{:else}
  {@render row()}
{/if}
