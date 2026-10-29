
<script lang="ts" module>
  export interface RadioOption {
    value: string;
    label: string;
    hint?: string;
    disabled?: boolean;
  }
</script>

<script lang="ts">
  import type { Snippet } from 'svelte';
  import Radio from './Radio.svelte';
  import { provideRadioGroup } from './radio-context';

  interface Props {
    value?: string;
    label?: string;
    labelledby?: string;
    options?: readonly RadioOption[];
    orientation?: 'vertical' | 'horizontal';
    disabled?: boolean;
    name?: string;
    onchange?: (value: string) => void;
    children?: Snippet;
  }

  const uid = $props.id();
  let {
    value = $bindable(''), label, labelledby, options, orientation = 'vertical', disabled = false,
    name = `oc-radio-group-${uid}`, onchange, children,
  }: Props = $props();

  provideRadioGroup({
    get name() { return name; },
    get value() { return value; },
    get disabled() { return disabled; },
    select(next: string) {
      value = next;
      onchange?.(next);
    },
  });
</script>

<div class="oc-radio-group" role="radiogroup" aria-label={label} aria-labelledby={labelledby} data-orientation={orientation}>
  {#if options}
    {#each options as option (option.value)}
      <Radio value={option.value} label={option.label} hint={option.hint} disabled={option.disabled} />
    {/each}
  {:else if children}
    {@render children()}
  {/if}
</div>
