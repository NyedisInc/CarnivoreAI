<!-- <button role="radio" aria-checked data-btn="quiet"> label: ' -->
<script lang="ts" module>
  export interface SegmentedOption {
    value: string;
    label: string;
    icon?: string;
    disabled?: boolean;
    attrs?: Record<string, string>;
  }
</script>

<script lang="ts">
  import type { HTMLAttributes } from 'svelte/elements';
  import Icon from '../../opscenter/ui/Icon.svelte';
  import Button from './Button.svelte';

  interface Props extends Omit<HTMLAttributes<HTMLDivElement>, 'class' | 'children' | 'role' | 'onchange'> {
    options: readonly SegmentedOption[];
    value?: string;
    label?: string;
    labelledby?: string;
    size?: 'sm' | 'md';
    fill?: boolean;
    iconOnly?: boolean;
    disabled?: boolean;
    onchange?: (value: string) => void;
  }

  let { options, value = $bindable(''), label, labelledby, size = 'sm', fill = false, iconOnly = false, disabled = false, onchange, ...rest }: Props = $props();

  let group = $state<HTMLDivElement | undefined>();

  const enabled = (option: SegmentedOption): boolean => !disabled && !option.disabled;
  const stop = $derived(
    options.find((o) => o.value === value && enabled(o))?.value ?? options.find(enabled)?.value,
  );

  function choose(next: string): void {
    if (next === value) return;
    value = next;
    onchange?.(next);
  }

  function key(event: KeyboardEvent): void {
    const from = (event.target as HTMLElement).closest<HTMLElement>('[role="radio"]');
    const reachable = options.filter(enabled);
    if (!from || reachable.length === 0) return;
    const at = reachable.findIndex((o) => o.value === from.dataset.value);
    let to: number;
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') to = (at + 1) % reachable.length;
    else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') to = (at - 1 + reachable.length) % reachable.length;
    else if (event.key === 'Home') to = 0;
    else if (event.key === 'End') to = reachable.length - 1;
    else return;
    event.preventDefault();
    const target = reachable[to];
    if (!target) return;
    choose(target.value);
    [...(group?.querySelectorAll<HTMLElement>('[role="radio"]') ?? [])].find((el) => el.dataset.value === target.value)?.focus();
  }
</script>

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<div {...rest} bind:this={group} class="oc-segmented" role="radiogroup" aria-label={label} aria-labelledby={labelledby}
  data-fill={fill || undefined} data-icon-only={iconOnly || undefined} onkeydown={key}>
  {#each options as option (option.value)}
    <Button {...option.attrs} variant="quiet" size={size === 'sm' ? 'sm' : 'md'} role="radio" aria-checked={option.value === value}
      tabindex={option.value === stop ? 0 : -1} disabled={!enabled(option)} data-value={option.value}
      aria-label={iconOnly && option.icon ? option.label : undefined} title={iconOnly && option.icon ? option.label : undefined}
      onclick={() => choose(option.value)}>
      {#if option.icon}<Icon name={option.icon} size={iconOnly ? 14 : 12} />{/if}{#if !(iconOnly && option.icon)}{option.label}{/if}
    </Button>
  {/each}
</div>
