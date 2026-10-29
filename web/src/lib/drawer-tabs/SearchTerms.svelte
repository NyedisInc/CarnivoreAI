
<script lang="ts">
  import Button from '../base/Button.svelte';
  import { t } from '../i18n/index.svelte';
  import type { DeepSearchController } from '../deepsearch/deepsearch.svelte';
  import { SUGGEST_ID_PREFIX, SUGGEST_LIST_ID } from '../deepsearch/deepsearch.svelte';

  interface Props {
    controller: DeepSearchController;
    active?: boolean;
  }
  let { controller, active = false }: Props = $props();
</script>

{#if controller.suggestions.length > 0}
  <div class="ds-terms" id={SUGGEST_LIST_ID} role="listbox" aria-orientation="horizontal" aria-label={t('drawer.search.terms.aria')} data-testid="search-terms">
    <span class="ds-terms__label" aria-hidden="true">{t('drawer.search.terms.label')}</span>
    {#each controller.suggestions as row, i (row.term)}
      <Button
        size="sm"
        id={`${SUGGEST_ID_PREFIX}${i}`}
        role="option"
        tabindex={-1}
        aria-selected={i === controller.suggestActive}
        data-active={active && i === controller.suggestActive ? '1' : undefined}
        title={t('drawer.search.terms.count', { count: row.docs })}
        onmousedown={(e: MouseEvent) => e.preventDefault()}
        onclick={() => controller.acceptSuggestion(i)}
      >{row.term}<span class="ds-terms__n">{row.docs}</span></Button>
    {/each}
  </div>
{/if}

<style>
  @layer components {
    .ds-terms {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: var(--oc-space-1);
      padding-top: var(--oc-space-1-5);
    }

    .ds-terms__label {
      margin-inline-end: var(--oc-space-0-5);
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-micro);
      letter-spacing: var(--oc-tracking-caps);
      text-transform: uppercase;
    }

    .ds-terms__n {
      margin-inline-start: var(--oc-space-1);
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-micro);
    }

    .ds-terms :global([data-btn][data-active='1']) {
      border-color: color-mix(in oklab, var(--oc-line-rule) var(--oc-focus-keep, 75%), var(--oc-focus-lift, currentColor));
      color: var(--oc-text-bright);
    }
  }
</style>
