
<script lang="ts">
  import Button from '../base/Button.svelte';
  import IconButton from '../base/IconButton.svelte';
  import Switch from '../base/Switch.svelte';
  import { t } from '../i18n/index.svelte';
  import { ageWords } from '../computers/computers-format';
  import { packMachines } from '../pack-machines/pack-machines-store.svelte';
  import { moveInOrder, orderEditable, situationOf, strandedCount, successorOrder, takeoverReasonKey, type RosterComputer } from './roster-model';
  import { confirmInterim, reconnectActivity, saveOrder, setEligible, setRelay, setTakeover } from './reconnect-store.svelte';

  const { list, nowMs }: { list: readonly RosterComputer[]; nowMs: number } = $props();
  const view = $derived(packMachines.data);
  const situation = $derived(situationOf(view));
  const editable = $derived(orderEditable(view));
  const order = $derived(successorOrder(list));
  const reason = $derived(takeoverReasonKey(view));
  const interim = $derived(view?.interim === true);
  const relayOn = $derived(view?.reconnect?.relay_on === true);
  const takeoverOn = $derived(view?.reconnect?.takeover_on === true);
  const main = $derived(list.find((c) => c.isAlpha) ?? null);
  const stranded = $derived(strandedCount(list));
  const since = $derived(view?.roster_issued_at ? ageWords(new Date(view.roster_issued_at * 1000).toISOString(), nowMs) : null);
  const busy = $derived(reconnectActivity.busy !== null);
</script>

{#if view?.reconnect}
  <section class="m1-sec" data-sec="reconnect"><h3 class="pp-k">{t('roster.reconnect.title')}</h3>
    {#if main}
      <p class="pp-hint" data-line="state">{view.generation != null && since
        ? t('roster.reconnect.state', { main: main.name, generation: view.generation, since })
        : t('roster.reconnect.state_plain', { main: main.name })}</p>
    {/if}
    {#if situation !== 'normal'}<p class="pp-warn" data-line="situation" data-situation={situation}>{t(`roster.reconnect.situation.${situation}`)}</p>{/if}
    {#if interim}
      <p class="pp-warn" data-line="interim">{t('roster.reconnect.interim')}</p>
      <div class="pp-acts"><Button variant="confirm" data-act="confirm-main" disabled={busy} onclick={() => void confirmInterim()}>{t('roster.reconnect.confirm')}</Button></div>
      <p class="pp-hint">{t('roster.reconnect.confirm_note')}</p>
    {/if}
    <div class="pp-swrow"><span class="pp-swrow__label">{t('roster.reconnect.relay')}</span>
      <Switch bare label="" disabled={busy} bind:checked={() => relayOn, (next) => void setRelay(next)} aria-label={t('roster.reconnect.relay')} data-act="relay" /></div>
    <p class="pp-hint">{t('roster.reconnect.relay_note')}</p>
    <div class="pp-swrow"><span class="pp-swrow__label">{t('roster.reconnect.takeover')}</span>
      <Switch bare label="" disabled={busy} bind:checked={() => takeoverOn, (next) => void setTakeover(next, relayOn)} aria-label={t('roster.reconnect.takeover')} data-act="takeover" /></div>
    {#if reason !== 'unknown'}<p class="pp-hint" data-line="takeover-reason" data-reason={reason}>{t(`roster.reconnect.takeover_${reason}`)}</p>{/if}
    {#if order.length > 1}
      <h3 class="pp-k">{t('roster.reconnect.order')}</h3>
      <p class="pp-hint">{editable ? t('roster.reconnect.order_hint') : t('roster.reconnect.order_readonly')}</p>
      <ul class="pp-grants" data-list="successors">
        {#each order as c, i (c.id)}
          <li class="pp-swrow" data-successor={c.id}>
            <span>{i + 1}. {c.name}{#if c.viaRelay} <span class="pp-dim">{t('roster.reconnect.via_relay')}</span>{/if}{#if c.needsUpdate} <span class="pp-warn" data-flag="needs-update">{t('roster.reconnect.needs_update')}</span>{/if}</span>
            {#if editable}
              <Switch bare label="" disabled={busy || c.needsUpdate} bind:checked={() => c.eligible, (next) => void setEligible(c.id, next)} aria-label={t('roster.reconnect.eligible', { name: c.name })} data-act="eligible" />
              <IconButton label={t('roster.reconnect.up', { name: c.name })} icon="chevron-up" iconSize={12} variant="quiet" disabled={busy || i === 0}
                onclick={() => void saveOrder(moveInOrder(order.map((o) => o.id), c.id, -1))} />
              <IconButton label={t('roster.reconnect.down', { name: c.name })} icon="chevron-down" iconSize={12} variant="quiet" disabled={busy || i === order.length - 1}
                onclick={() => void saveOrder(moveInOrder(order.map((o) => o.id), c.id, 1))} />
            {:else if c.eligible}<span class="pp-dim">{t('roster.reconnect.opted_in')}</span>{/if}
          </li>
        {/each}
      </ul>
      {#if stranded > 0}<p class="pp-hint" data-line="stranded">{t('roster.reconnect.stranded', { n: stranded })}</p>{/if}
    {/if}
    {#if reconnectActivity.error}<p class="pp-err" role="alert">{reconnectActivity.error}</p>{/if}
  </section>
{/if}
