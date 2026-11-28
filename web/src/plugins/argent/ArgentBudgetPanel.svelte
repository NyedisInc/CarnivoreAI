
<script lang="ts">
    import { onDestroy } from 'svelte';
    import { t as reactiveT, authFetch, resourcePush, failureReason, formatMicros, loadBudgetRequests, type BudgetRequestRow, type Translate } from '../sdk';
    import { BudgetAskForm, Button, State } from '../sdk/ui';

    interface Budget { state: string; spent_micros: number | null; cap_micros: number | null; owner_name: string; effective_spent_micros: number | null; governing_item_id?: string; governing_item_title?: string }
    interface Item { name: string; held: boolean; budget: Budget | null }
    interface Props { t?: Translate; fetcher?: typeof authFetch; pollMs?: number; open?: (url: string) => void }
    const { t = reactiveT, fetcher = authFetch, pollMs = 30000, open = (url) => void window.open(url, '_blank', 'noopener,noreferrer') }: Props = $props();

    let items = $state<Record<string, Item>>({});
    let requests = $state<BudgetRequestRow[]>([]);
    const askFor = /\?ask=([^&#]+)$/.exec(typeof window === 'undefined' ? '' : window.location.hash)?.[1];
    const askItem = askFor ? decodeURIComponent(askFor) : '';
    let busy = $state(false);
    let problem = $state('');
    let said = $state('');

    const held = $derived(Object.entries(items).filter(([, item]) => item.held || item.budget?.state === 'paused'));

    async function load(): Promise<void> {
        try {
            const body = await fetcher<{ items?: Record<string, Item> }>('/argent/cost');
            items = body && typeof body.items === 'object' && body.items ? body.items : {};
        } catch (error) {
            problem = failureReason(error);
        }
    }
    async function loadRequests(): Promise<void> {
        try {
            requests = await loadBudgetRequests(fetcher as (path: string) => Promise<unknown>);
        } catch {
        }
    }
    void load();
    void loadRequests();
    onDestroy(resourcePush().pushOrPoll(() => { void load(); void loadRequests(); }, pollMs, ['argent_cost', 'argent_budget_requests']));

    async function liftInArgent(id: string, item: Item): Promise<void> {
        busy = true;
        problem = said = '';
        try {
            const reply = await fetcher<{ url?: string | null }>('/argent/budget/lift', { method: 'POST', body: JSON.stringify({ item_id: item.budget?.governing_item_id || id }) });
            if (reply?.url) open(reply.url);
            else said = t('argent.cost.lift_in_argent_hint');
        } catch (error) {
            problem = failureReason(error);
        } finally {
            busy = false;
        }
    }

    function governedText(item: Item): string {
        return item.budget?.governing_item_title ? t('argent.cost.governed_by', { title: item.budget.governing_item_title }) : t('argent.cost.governed_above');
    }
</script>

{#if held.length}
    <div data-argent="budgets">
        <p class="tm__sub">{t('argent.cost.heading')}</p>
        {#each held as [id, item] (id)}
            <p class="tm__sub" data-argent="budget-row">
                {#if item.budget?.owner_name}
                    {t('argent.cost.row', { item: item.name, spent: formatMicros(item.budget?.effective_spent_micros ?? item.budget?.spent_micros), cap: formatMicros(item.budget?.cap_micros), owner: item.budget.owner_name })}
                {:else}
                    {t('argent.cost.row_governed', { item: item.name, governed: governedText(item) })}
                {/if}
            </p>
            <div class="tm__actions">
                <BudgetAskForm itemId={id} capMicros={item.budget?.cap_micros ?? null} spentMicros={item.budget?.effective_spent_micros ?? item.budget?.spent_micros ?? null} held owner={item.budget?.owner_name ?? ''} {requests} {fetcher} startOpen={askItem === id} onsent={() => void loadRequests()} />
                <Button size="sm" variant="confirm" disabled={busy} data-argent="lift" onclick={() => void liftInArgent(id, item)}>{t('argent.cost.lift_in_argent')}</Button>
            </div>
        {/each}
        {#if said}<p class="tm__sub" role="status" data-argent="said">{said}</p>{/if}
        {#if problem}<State kind="error" inline title={problem} data-argent="budget-problem" />{/if}
    </div>
{/if}
