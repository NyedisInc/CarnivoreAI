
<script lang="ts">
  import Button from '../base/Button.svelte';
  import Field from '../base/Field.svelte';
  import { t } from '../i18n/index.svelte';
  import { authFetch } from '../../opscenter/api/auth.svelte';
  import { failureReason } from '../errors/failure-reason';
  import { formatMicros } from './money';
  import { defaultAsk, MAX_ASK_MICROS, MAX_REASON_CHARS, parseDollars, pendingFor, type BudgetRequestRow } from './budget-ask';

  interface Props {
    itemId: string;
    capMicros?: number | null;
    spentMicros?: number | null;
    held?: boolean;
    owner?: string;
    requests?: readonly BudgetRequestRow[];
    startOpen?: boolean;
    fetcher?: typeof authFetch;
    onsent?: () => void;
  }
  const { itemId, capMicros = null, spentMicros = null, held = false, owner = '', requests = [], startOpen = false, fetcher = authFetch, onsent }: Props = $props();

  let open = $state(startOpen);
  let amount = $state(defaultAsk(capMicros, spentMicros, held));
  let reason = $state('');
  let busy = $state(false);
  let said = $state('');
  let amountError = $state('');
  let reasonError = $state('');
  let justAsked = $state<number | null>(null);
  let justAskedId = $state<string | null>(null);

  const waiting = $derived(pendingFor(requests, itemId));
  const askedMicros = $derived(waiting ? waiting.requested_micros : justAsked !== null && !requests.some((r) => r.id === justAskedId) ? justAsked : null);
  const who = $derived(owner || t('argent.cost.ask_unavailable_owner'));

  async function send(): Promise<void> {
    const micros = parseDollars(amount);
    const text = reason.trim();
    amountError = micros === null ? t('argent.cost.ask_amount_invalid', { max: formatMicros(MAX_ASK_MICROS) }) : '';
    reasonError = text.length < 1 || text.length > MAX_REASON_CHARS ? t('argent.cost.ask_reason_invalid', { max: String(MAX_REASON_CHARS) }) : '';
    if (micros === null || reasonError) return;
    busy = true;
    said = '';
    try {
      const filed = await fetcher<{ id?: string }>('/argent/budget/requests', { method: 'POST', body: JSON.stringify({ item_id: itemId, amount_micros: micros, reason: text }) });
      justAskedId = filed?.id ?? null;
      justAsked = micros;
      open = false;
      reason = '';
      said = t('argent.cost.sent');
      onsent?.();
    } catch (error) {
      const code = (error as { code?: unknown } | null)?.code;
      if (code === 'budget_request_unavailable') said = t('argent.cost.ask_unavailable', { owner: who });
      else if (code === 'budget_request_pending') { said = t('argent.cost.ask_already', { owner: who }); onsent?.(); }
      else said = failureReason(error);
    } finally {
      busy = false;
    }
  }
</script>

<span class="baf" data-argent-ask={itemId}>
  {#if askedMicros !== null}
    <span class="baf-note" role="status" data-argent-asked>{t('argent.cost.ask_pending', { amount: formatMicros(askedMicros), owner: who })}</span>
  {:else if !open}
    <Button size="sm" disabled={busy} data-argent="ask" data-argent-lift-ask onclick={() => { open = true; said = ''; }}>{t('argent.cost.ask')}</Button>
  {:else}
    <span class="baf-fields" data-argent-ask-form>
      <Field label={t('argent.cost.ask_amount')} bind:value={amount} error={amountError} inputmode="decimal" disabled={busy} data-argent-ask-amount />
      <Field label={t('argent.cost.ask_reason')} bind:value={reason} error={reasonError} multiline rows={2} maxlength={MAX_REASON_CHARS} disabled={busy} data-argent-ask-reason />
      <span class="baf-actions">
        <Button size="sm" variant="confirm" disabled={busy} data-argent-ask-send onclick={() => void send()}>{t('argent.cost.ask_send')}</Button>
        <Button size="sm" disabled={busy} data-argent-ask-cancel onclick={() => { open = false; }}>{t('argent.cost.ask_cancel')}</Button>
      </span>
    </span>
  {/if}
  {#if said}<span class="baf-note" role="status" data-argent-ask-said>{said}</span>{/if}
</span>

<style>
  @layer components {
    .baf { display: inline-flex; flex-wrap: wrap; align-items: center; gap: var(--oc-space-2); min-width: 0; max-width: 100%; }
    .baf-fields { display: flex; flex-direction: column; gap: var(--oc-space-2); min-width: 0; width: min(100%, 28rem); }
    .baf-actions { display: flex; flex-wrap: wrap; gap: var(--oc-space-2); }
    .baf-note { color: var(--oc-text-muted); min-width: 0; overflow-wrap: anywhere; }
  }
</style>
