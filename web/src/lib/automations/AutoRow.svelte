
<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import Button from '../base/Button.svelte';
  import BaseListRow from '../base/ListRow.svelte';
  import Switch from '../base/Switch.svelte';
  import Tag from '../base/Tag.svelte';
  import { pageRowMenu, type PageRowMenu } from '../item-menu/page-row';
  import Mark from './Mark.svelte';
  import RunStrip from './RunStrip.svelte';
  import type { Automation } from './api';
  import { runNow, toggleEnabled, view } from './list-state.svelte';
  import { attentionWords, rateWords } from './logic/signals';
  import { lightOf } from './logic/marks';
  import type { ListRow } from './logic/list';
  import { isLive, runTime, secsWords, statusWord } from './logic/words';
  import { data, pageClock } from './page-store.svelte';

  type Props = {
    automation: Automation; row: ListRow; selected: boolean; onPick: (event: MouseEvent) => void; menu: () => PageRowMenu | null;
  };
  let { automation, row, selected, onPick, menu }: Props = $props();

  const sig = $derived(row.sig);
  const last = $derived(sig.last);
  const live = $derived(!!last && isLive(last.status));
  const light = $derived(lightOf(row.enabled, data.paused, last?.status ?? null));
  const clock = $derived(pageClock());
  const next = $derived(!row.enabled ? t('automations.page.row.next_off') : data.paused ? t('automations.page.row.next_paused') : automation.next_fire_at ? clock.short(automation.next_fire_at, data.now) : t('automations.page.row.next_none'));
  const showRel = $derived(!!automation.next_fire_at && row.enabled && !data.paused);
  const current = $derived(data.paneOpen && data.selectedId === row.id ? (data.paneRunId ?? last?.run_id ?? null) : null);
  const busy = $derived(live || view.busyId === row.id);
</script>

<BaseListRow class="ap-row" role="row" data-automation={row.id} aria-selected={selected} tabindex={-1} onclick={onPick} {...pageRowMenu(menu)}>
  <span class="ap-c-light" role="gridcell">
    {#if light.kind === 'run'}<Mark status={light.status} size={10} />{:else}<Mark light={light.kind} size={10} label={light.kind === 'off' && data.paused && row.enabled ? t('automations.page.sentence.paused') : undefined} />{/if}
  </span>
  <span class="ap-c-name" role="gridcell">
    <span class="ap-nm-line">
      <span class="ap-nm">{row.name}</span>
      {#if sig.attention}
        <Tag data-attention-tag title={t('automations.page.attention.title', { rule: attentionWords(sig.attention) })}>{attentionWords(sig.attention)}</Tag>
      {/if}
    </span>
    <span class="ap-l2"><span>{row.cronWords}</span></span>
  </span>
  <span class="ap-c-next ap-num" role="gridcell" data-automation-next>
    <span>{next}</span>
    {#if showRel}<span class="ap-sub">{clock.rel(automation.next_fire_at, data.now)}</span>{/if}
  </span>
  <span class="ap-c-last" role="gridcell">
    {#if !last}
      <span class="ap-dim">{t('automations.page.row.never_ran')}</span>
    {:else}
      <span class="ap-lr" data-status={last.status}>
        <Mark status={last.status} size={10} />
        <span class:ap-num={!live}>{live ? statusWord(last.status) : clock.rel(runTime(last), data.now)}</span>
      </span>
      {#if last.status === 'failed' || last.status === 'skipped'}<span class="ap-sub">{statusWord(last.status)}</span>{/if}
    {/if}
  </span>
  <span class="ap-c-strip" role="gridcell"><RunStrip runs={automation.recent ?? []} {current} /></span>
  <span class="ap-c-rate ap-num" role="gridcell" title={t('automations.page.rate.title')}>{rateWords(sig.rate)}</span>
  <span class="ap-c-med ap-num" role="gridcell">{sig.median == null ? t('automations.page.row.took_none') : secsWords(sig.median)}</span>
  <span class="ap-c-on" role="gridcell">
    <Switch
      bare
      label={t(row.enabled ? 'automations.page.row.on' : 'automations.page.row.off')}
      aria-label={t('automations.page.row.switch_aria', { name: row.name })}
      data-sw={row.id}
      disabled={view.busyId === row.id}
      bind:checked={() => row.enabled, () => void toggleEnabled(automation)}
    />
  </span>
  <span class="ap-c-act oc-list__actions" role="gridcell">
    <Button variant="confirm" size="sm" data-run={row.id} disabled={busy} onclick={() => void runNow(automation)}>
      {t(busy ? 'automations.page.row.running' : 'automations.page.row.run_now')}
    </Button>
  </span>
</BaseListRow>
