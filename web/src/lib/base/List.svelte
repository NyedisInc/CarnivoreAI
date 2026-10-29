
<script lang="ts" module>
  export type ListDensity = 'dense' | 'default' | 'roomy';
</script>

<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { HTMLAttributes } from 'svelte/elements';

  interface Props extends Omit<HTMLAttributes<HTMLDivElement>, 'class' | 'children'> {
    density?: ListDensity;
    label?: string;
    role?: string;
    class?: string;
    children: Snippet;
    element?: HTMLDivElement;
  }

  let {
    density = 'default', label, role = 'list', class: extra = '', children, element = $bindable(), ...rest
  }: Props = $props();
</script>

<div bind:this={element} {...rest} class={['oc-list', extra]} {role} aria-label={label} data-density={density}>{@render children()}</div>
