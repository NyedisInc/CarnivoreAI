<script lang="ts">
  import { t } from '../sdk';
  import { baseField } from './task-manager-base-field';
  import { Icon } from '../sdk/ui';
  import { clearViewFilter, setViewQuery, viewFilter, viewFilterActive } from './task-manager-view-filter.svelte';

  let open = $state(false);
  let field = $state<HTMLInputElement | null>(null);
  const shown = $derived(open || viewFilter.query !== '');

  function toggle(): void {
    if (shown) {
      open = false;
      setViewQuery('');
      return;
    }
    open = true;
    queueMicrotask(() => field?.focus());
  }

  function onKey(event: KeyboardEvent): void {
    if (event.key !== 'Escape') return;
    event.preventDefault();
    toggle();
  }
</script>

<button type="button" class="hds-key" aria-pressed={shown} aria-label={t('cplug.huddle.search.key')} title={t('cplug.huddle.search.key')}
        data-task-manager-search-key onclick={toggle}><Icon name="search" size={12} strokeWidth={1.75} /></button>
{#if viewFilterActive()}
  <button type="button" class="hds-key hds-key--clear" aria-label={t('cplug.huddle.search.clear')} title={t('cplug.huddle.search.clear')}
          data-task-manager-filter-clear onclick={() => { open = false; clearViewFilter(); }}><Icon name="close" size={12} strokeWidth={1.75} /></button>
{/if}
{#if shown}
  <input bind:this={field} class="oc-field hds-field" use:baseField={'sm'} type="search" autocomplete="off" spellcheck="false" value={viewFilter.query}
         placeholder={t('cplug.huddle.search.placeholder')} aria-label={t('cplug.huddle.search.placeholder')} data-task-manager-search
         oninput={(event) => setViewQuery((event.currentTarget as HTMLInputElement).value)} onkeydown={onKey} />
{/if}

<style>
  @layer components {
    .hds-key {
      display: inline-flex;
      flex: none;
      align-items: center;
      justify-content: center;
      width: 22px;
      height: 20px;
      padding: 0;
      border: 0;
      background: none;
      color: var(--oc-text-dim);
      cursor: pointer;
    }

    .hds-key:hover {
      color: var(--oc-text-bright);
    }

    .hds-key[aria-pressed='true'] {
      color: var(--oc-cyan);
    }

    .hds-key--clear {
      color: var(--oc-coral);
    }

    .hds-field {
      flex: 1 0 100%;
      min-width: 0;
      height: 20px;
      font-size: var(--oc-fs-label);
    }
  }
</style>
