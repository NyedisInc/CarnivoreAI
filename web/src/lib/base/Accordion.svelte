
<script lang="ts" module>
  export interface AccordionItem {
    value: string;
    label: string;
    count?: number | string;
    disabled?: boolean;
  }
</script>

<script lang="ts">
  import { Accordion } from 'bits-ui';
  import type { Snippet } from 'svelte';
  import FoldChevron from '../../opscenter/ui/FoldChevron.svelte';

  interface Props {
    items: readonly AccordionItem[];
    type?: 'single' | 'multiple';
    value?: string | string[];
    headingLevel?: 2 | 3 | 4 | 5 | 6;
    panel: Snippet<[AccordionItem]>;
  }

  let { items, type = 'multiple', value = $bindable(type === 'multiple' ? [] : ''), headingLevel = 3, panel }: Props =
    $props();
</script>

{#snippet folds()}
  {#each items as item (item.value)}
    <Accordion.Item class="oc-fold" value={item.value} disabled={item.disabled}>
      <Accordion.Header class="oc-fold__head" level={headingLevel}>
        <Accordion.Trigger class="oc-fold__toggle" data-btn="row">
          <span class="oc-fold__label">{item.label}</span>
          {#if item.count !== undefined}<span class="oc-fold__count">{item.count}</span>{/if}
          <FoldChevron />
        </Accordion.Trigger>
      </Accordion.Header>
      <Accordion.Content class="oc-fold__panel">{@render panel(item)}</Accordion.Content>
    </Accordion.Item>
  {/each}
{/snippet}

{#if type === 'single'}
  <Accordion.Root class="oc-accordion" type="single" bind:value={() => value as string, (v) => (value = v)}>{@render folds()}</Accordion.Root>
{:else}
  <Accordion.Root class="oc-accordion" type="multiple" bind:value={() => value as string[], (v) => (value = v)}>{@render folds()}</Accordion.Root>
{/if}
