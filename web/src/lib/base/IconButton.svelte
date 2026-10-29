<!-- <button> -->
<script lang="ts" module>
  export type IconButtonVariant = 'secondary' | 'quiet' | 'close' | 'float' | 'danger';
</script>

<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { HTMLButtonAttributes } from 'svelte/elements';
  import Icon from '../../opscenter/ui/Icon.svelte';
  import Button from './Button.svelte';

  interface Props extends Omit<HTMLButtonAttributes, 'class' | 'children' | 'title' | 'aria-label' | 'aria-pressed'> {
    label: string;
    icon?: string;
    iconSize?: number;
    variant?: IconButtonVariant;
    pressed?: boolean;
    element?: HTMLElement | null;
    children?: Snippet;
  }

  let { label, icon, iconSize = 12, variant = 'secondary', pressed, element = $bindable(null), children, ...rest }: Props = $props();

  const base = $derived(variant === 'secondary' ? 'secondary' : 'quiet');
  const tone = $derived(variant === 'close' || variant === 'float' || variant === 'danger' ? variant : undefined);
</script>

<Button bind:element {...rest} variant={base} size="icon" aria-label={label} title={label} aria-pressed={pressed} data-tone={tone}>
  {#if children}{@render children()}{:else if icon}<Icon name={icon} size={iconSize} />{/if}
</Button>
