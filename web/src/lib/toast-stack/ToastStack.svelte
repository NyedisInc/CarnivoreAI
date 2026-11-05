
<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import { bindToastManager, currentManager, currentView } from './toast-stack-store.svelte';
  import ToastCard from './ToastCard.svelte';

  $effect(() => bindToastManager());

  const view = $derived(currentView());
  const manager = $derived(currentManager());
</script>

{#if manager}
  {#if view.dismissAll}
    {@const all = view.dismissAll}
    
    <button type="button" class="toast-dismiss-all" data-btn="quiet" data-size="bare" data-overflow="visible"
      data-total={all.total} data-blocking={all.blocking}
      aria-label={all.blocking ? t('toast.dismiss_all.label_blocking', { total: all.total, blocking: all.blocking }) : t('toast.dismiss_all.label', { total: all.total })}
      onclick={() => manager.dismissAll()}>{t('toast.dismiss_all.text', { total: all.total })}</button>
  {/if}
  {#if view.waiting}
    <div class="toast-waiting" role="status" data-count={view.waiting}>{t('toast.detailed.waiting', { count: view.waiting })}</div>
  {/if}
  {#each view.cards as card (card.uid)}
    <ToastCard {card} {manager} />
  {/each}
  {#if view.overflow}
    {@const more = view.overflow}
    <button type="button" class="toast-overflow" data-btn="quiet" data-size="bare" data-overflow="visible"
      data-hidden-count={more.expanded ? 0 : more.count} data-worst-severity={more.worst} data-severity={more.worst}
      aria-expanded={more.expanded} onclick={() => manager.toggleOverflow()}>
      {#if more.expanded}
        {t('toast.show_fewer')}
      {:else}
        <span class="toast-overflow__count">{t('toast.overflow.more', { count: more.count })}</span>
        
        {#if more.worstCount !== null}<span class="toast-overflow__worst">{t('toast.overflow.worst', { count: more.worstCount })}</span>{/if}
      {/if}
    </button>
  {/if}
{/if}
