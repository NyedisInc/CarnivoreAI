
<script lang="ts">
  import { t } from '../../i18n/index.svelte';
  import type { Automation } from '../api';
  import Button from '../../base/Button.svelte';
  import Switch from '../../base/Switch.svelte';
  import ConfirmPopup from '../../dialog-frame/ConfirmPopup.svelte';
  import Mark from '../Mark.svelte';
  import { pageRowMenu, type PageRowMenu } from '../../item-menu/page-row';
  import { automationMenuNodes, type RowMenuAction } from '../row-menu-nodes';
  import { duplicate, kindWords, remove, rowOf, runNow, toggleEnabled, view } from '../list-state.svelte';
  import { lightOf } from '../logic/marks';
  import { isLive } from '../logic/words';
  import { data, openEdit, pageClock } from '../page-store.svelte';

  let { automation }: { automation: Automation } = $props();

  let deleting = $state(false);
  let top = $state<HTMLElement | null>(null);

  const row = $derived(rowOf(automation));
  const last = $derived(row.sig.last);
  const running = $derived(!!last && isLive(last.status) && last.status !== 'waiting_on_you');
  const light = $derived(lightOf(automation.enabled, data.paused, last?.status ?? null));
  const words = $derived(
    !automation.enabled
      ? t('automations.page.pane.status_off')
      : data.paused
        ? t('automations.page.pane.status_paused')
        : automation.next_fire_at
          ? t('automations.page.pane.status_on_next', { when: pageClock().short(automation.next_fire_at, data.now) })
          : t('automations.page.pane.status_on'),
  );
  const busy = $derived(view.busyId === automation.automation_id);

  function pick(action: RowMenuAction): void {
    if (action === 'edit') openEdit(automation.automation_id);
    else if (action === 'duplicate') void duplicate(automation);
    else deleting = true;
  }

  function headMenu(): PageRowMenu {
    return { type: 'pagerow', ctx: { label: t('automations.page.menu.aria'), nodes: automationMenuNodes(pick) } };
  }
</script>

<div data-pane-head {...pageRowMenu(headMenu)}>
  
  <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
  <div class="ap-pn-top" tabindex="-1" bind:this={top}>
    <div class="ap-pn-status">
      {#if light.kind === 'run'}<Mark status={light.status} size={14} />{:else}<Mark light={light.kind} size={14} />{/if}
      <span data-pane-status>{words}</span>
    </div>
  </div>
  <h2 class="ap-pn-name" data-pane-name>{automation.name}</h2>
  <div class="ap-pn-meta">
    <span>{kindWords(automation.target.kind)}</span>
    <span>{row.cronWords}</span>
    <span class="ap-pn-dim ap-num">{automation.trigger.cron}</span>
  </div>
  {#if automation.description}<p class="ap-pn-one">{automation.description}</p>{/if}

  <div class="ap-pn-actions">
    <Switch
      label={t(automation.enabled ? 'automations.page.row.on' : 'automations.page.row.off')}
      aria-label={t('automations.page.row.switch_aria', { name: automation.name })}
      data-pane-toggle
      disabled={busy}
      bind:checked={() => automation.enabled, () => void toggleEnabled(automation)}
    />
    <Button variant="confirm" size="sm" data-pane-run disabled={running || busy} onclick={() => void runNow(automation)}>
      {t(running ? 'automations.page.pane.running' : 'automations.page.pane.run_now')}
    </Button>
    <Button size="sm" data-pane-edit onclick={() => openEdit(automation.automation_id)}>{t('automations.page.pane.edit')}</Button>
  </div>
  <p class="ap-pn-note" data-pane-note>{t(automation.spends ? 'automations.page.reader.spends' : 'automations.page.reader.spends_none')}</p>
</div>
{#if deleting}
  <ConfirmPopup
    label={t('automations.page.pane.delete_aria', { name: automation.name })}
    message={t('automations.page.pane.delete_confirm', { name: automation.name })}
    anchor={top}
    cancelLabel={t('automations.page.pane.cancel')}
    confirmLabel={t('automations.page.pane.delete')}
    data-pane-delete
    confirmProps={{ 'data-pane-delete-yes': '' }}
    cancelProps={{ 'data-pane-delete-no': '' }}
    onConfirm={() => void remove(automation)}
    onCancel={() => (deleting = false)}
  />
{/if}
