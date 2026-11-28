
<script lang="ts" module>
  export type IconButtonVariant = 'secondary' | 'quiet' | 'close' | 'float' | 'danger' | 'strong';
</script>

<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { HTMLButtonAttributes } from 'svelte/elements';
  import Icon from '../../opscenter/ui/Icon.svelte';
  import Button from './Button.svelte';

  interface Props extends Omit<HTMLButtonAttributes, 'class' | 'children' | 'title' | 'aria-label' | 'aria-pressed'> {
    label: string;
    tooltip?: string;
    icon?: string;
    iconSize?: number;
    iconStroke?: number;
    variant?: IconButtonVariant;
    pressed?: boolean;
    active?: boolean;
    element?: HTMLElement | null;
    children?: Snippet;
  }

  let { label, tooltip, icon, iconSize = 12, iconStroke, variant = 'secondary', pressed, active, element = $bindable(null), children, ...rest }: Props = $props();

  const base = $derived(variant === 'secondary' || variant === 'strong' ? 'secondary' : 'quiet');
  const tone = $derived(variant === 'close' || variant === 'float' || variant === 'danger' || variant === 'strong' ? variant : undefined);
</script>

<Button bind:element {...rest} variant={base} size="icon" aria-label={label} title={tooltip ?? label} aria-pressed={pressed} data-tone={tone} data-active={active ? '' : undefined}>
  {#if children}{@render children()}{:else if icon}<Icon name={icon} size={iconSize} strokeWidth={iconStroke} />{/if}
</Button>
