
<script lang="ts">
  import { Button as Bits, type ButtonRootProps } from 'bits-ui';
  import type { Snippet } from 'svelte';
  import type { HTMLButtonAttributes } from 'svelte/elements';
  import { buttonAttrs, type ButtonSize, type ButtonVariant } from './classes';
  import { titleWhenTruncated } from './truncate';

  interface Props extends Omit<HTMLButtonAttributes, 'class' | 'children'> {
    variant?: ButtonVariant;
    size?: ButtonSize;
    href?: string;
    element?: HTMLElement | null;
    children: Snippet;
  }

  let { variant = 'secondary', size = 'md', type = 'button', href, element = $bindable(null), children, ...rest }: Props = $props();

  $effect(() => (element ? titleWhenTruncated(element).destroy : undefined));

  const root = $derived(
    (href !== undefined ? { ...rest, href } : { ...rest, type }) as ButtonRootProps,
  );
</script>

<Bits.Root bind:ref={element} {...root} {...buttonAttrs(variant, size)}>{@render children()}</Bits.Root>
