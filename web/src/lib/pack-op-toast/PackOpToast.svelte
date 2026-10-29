
<script lang="ts">
  import './pack-op-toast.css';
  import { clock, startClock } from '../../opscenter/lib/frozen-clock.svelte';
  import { t } from '../i18n/index.svelte';
  import { Button, IconButton } from '../base';
  import { cancelOp, dismiss, shownOps, view } from './pack-op-store.svelte';
  import { barFraction, bytesLine, elapsed, etaLine, headline, logLine, outcomeLine, phaseOf, stepCount, stepLine, type PackOp } from './op-text';
  import { openMoved, openableId } from './open-moved';

  const ops = $derived(shownOps());
  const live = $derived(ops.some((o) => o.running));
  const now = $derived((clock.now, Date.now()));
  $effect(() => (live ? startClock() : undefined));

  function details(op: PackOp): void {
    view.details = { ...view.details, [op.id]: !view.details[op.id] };
  }

  function holdMiddle(event: MouseEvent, op: PackOp): void {
    if (event.button === 1 && !op.running) event.preventDefault();
  }

  /* middle click dismisses */
  function middleDismiss(event: MouseEvent, op: PackOp): void {
    if (event.button !== 1 || op.running) return;
    event.preventDefault();
    dismiss(op.id);
  }

  function fold(op: PackOp): void {
    view.folded = { ...view.folded, [op.id]: !view.folded[op.id] };
  }
</script>

{#if ops.length > 0}
  <div class="pot-dock" role="region" aria-label={t('pack.op.region')} data-pack-op-dock="">
    {#each ops as op (op.id)}
      {@const phase = phaseOf(op)}
      {@const folded = view.folded[op.id] === true}
      {@const note = view.note[op.id]}
      {@const outcome = outcomeLine(op)}
      {@const step = stepLine(op)}
      <section class="pot-card" data-phase={phase} data-op={op.id} role={phase === 'failed' ? 'alert' : 'status'}
        onmousedown={(event: MouseEvent) => holdMiddle(event, op)} onauxclick={(event: MouseEvent) => middleDismiss(event, op)}>
        <div class="pot-head">
          <span class="pot-label">{t('pack.op.label')}</span>
          <span class="pot-time" data-pot="time">{elapsed(op.started_at, op.finished_at, now)}</span>
          <IconButton variant="quiet" data-pot="fold" aria-expanded={!folded}
            label={t(folded ? 'pack.op.expand' : 'pack.op.collapse')} onclick={() => fold(op)}>{folded ? '+' : '-'}</IconButton>
        </div>
        <p class="pot-title" data-pot="title">{headline(op)}</p>
        {#if !folded}
          {#if step}
            <p class="pot-step" data-pot="step">{step}{#if stepCount(op)}{' '}<span class="pot-count">{stepCount(op)}</span>{/if}</p>
          {/if}
          {#if barFraction(op) !== null}
            <div class="pot-bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow={Math.round((barFraction(op) ?? 0) * 100)} data-pot="bar">
              <div class="pot-fill" style:width="{(barFraction(op) ?? 0) * 100}%"></div>
            </div>
            {#if bytesLine(op) || etaLine(op)}<p class="pot-meta" data-pot="meta">{bytesLine(op)}{#if bytesLine(op) && etaLine(op)}{', '}{/if}{etaLine(op)}</p>{/if}
          {/if}
          {#if outcome}<p class="pot-outcome" data-pot="outcome">{outcome}</p>{/if}
          {#if op.direction === 'in' && op.running}<p class="pot-step" data-pot="in">{t('pack.op.in_note', { machine: op.machine || '' })}</p>{/if}
          {#if note}<p class="pot-note" role="alert" data-pot="note">{note}</p>{/if}
          {#if view.details[op.id]}
            <ol class="pot-log" data-pot="log">
              {#each op.progress?.log ?? [] as line}<li>{logLine(line)}</li>{:else}<li>{t('pack.op.log_empty')}</li>{/each}
            </ol>
          {/if}
          <div class="pot-foot">
            <Button size="sm" data-pot="details" aria-expanded={view.details[op.id] === true} onclick={() => details(op)}>{t(view.details[op.id] ? 'pack.op.hide_details' : 'pack.op.details')}</Button>
            {#if op.running}
              {#if op.direction === 'out'}
                <Button variant="danger" size="sm" data-pot="cancel" disabled={view.cancelling[op.id] === true || op.cancel_blocked !== null}
                  onclick={() => void cancelOp(op.id)}>{t(view.cancelling[op.id] ? 'pack.op.cancelling' : 'pack.op.cancel')}</Button>
              {/if}
              {#if op.cancel_blocked && !note}<p class="pot-note" data-pot="blocked">{op.cancel_blocked}</p>{/if}
            {:else}
              {#if openableId(op)}
                <Button size="sm" data-pot="open" onclick={() => void openMoved(op)}>{t('pack.op.open')}</Button>
              {/if}
              <Button size="sm" data-pot="dismiss" onclick={() => dismiss(op.id)}>{t('pack.op.dismiss')}</Button>
            {/if}
          </div>
        {/if}
      </section>
    {/each}
  </div>
{/if}
