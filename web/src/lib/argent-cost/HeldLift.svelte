
<script lang="ts">
  import { onDestroy } from 'svelte';
  import Button from '../base/Button.svelte';
  import BudgetAskForm from './BudgetAskForm.svelte';
  import { loadBudgetRequests, type BudgetRequestRow } from './budget-ask';
  import { resourcePush } from '../resource-push/boot';
  import { t } from '../i18n/index.svelte';
  import { authFetch } from '../../opscenter/api/auth.svelte';
  import type { LiftView } from './cost-view';

  interface Props { itemId: string; lift: LiftView; fetcher?: typeof authFetch; open?: (url: string) => void }
  const { itemId, lift, fetcher = authFetch, open = (url) => void window.open(url, '_blank', 'noopener,noreferrer') }: Props = $props();

  let busy = $state(false);
  let said = $state('');

  let requests = $state<BudgetRequestRow[]>([]);

  async function loadRequests(): Promise<void> {
    try {
      requests = await loadBudgetRequests(fetcher as (path: string) => Promise<unknown>);
    } catch {
    }
  }
  void loadRequests();
  onDestroy(resourcePush().pushOrPoll(() => void loadRequests(), 60_000, ['argent_budget_requests']));

  async function liftInArgent(): Promise<void> {
    busy = true;
    said = '';
    try {
      const reply = await fetcher<{ url?: string | null }>('/argent/budget/lift', { method: 'POST', body: JSON.stringify({ item_id: lift.governingId || itemId }) });
      if (reply?.url) open(reply.url);
      else said = t('argent.card.lift_in_argent_hint');
    } catch {
      said = t('argent.card.lift_failed');
    } finally {
      busy = false;
    }
  }
</script>

<span class="hl" data-argent-lift={itemId}>
  {#if lift.isOwner}
    <Button size="sm" disabled={busy} data-argent-lift-open onclick={() => void liftInArgent()}>{t('argent.card.lift_in_argent')}</Button>
  {:else}
    <BudgetAskForm {itemId} capMicros={lift.capMicros ?? null} spentMicros={lift.spentMicros ?? null} held owner={lift.owner} {requests} {fetcher} onsent={() => void loadRequests()} />
    {#if !lift.owner}<span class="hl-said" data-argent-lift-governing>{lift.governingTitle ? t('argent.cost.governed_by', { title: lift.governingTitle }) : t('argent.cost.governed_above')}</span>{/if}
  {/if}
  {#if said}<span class="hl-said" role="status" data-argent-lift-said>{said}</span>{/if}
</span>

<style>
  .hl { display: inline-flex; flex-wrap: wrap; align-items: center; gap: var(--oc-space-2); }
  .hl-said { color: var(--oc-text-muted); }
</style>
