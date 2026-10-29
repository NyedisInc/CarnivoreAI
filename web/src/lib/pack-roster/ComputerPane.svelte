
<script lang="ts">
  import { tick } from 'svelte';
  import { t } from '../i18n/index.svelte';
  import Icon from '../../opscenter/ui/Icon.svelte';
  import IconButton from '../base/IconButton.svelte';
  import Tabs, { panelAttrs } from '../../opscenter/ui/Tabs.svelte';
  import { activity, remove } from '../computers/computers-store.svelte';
  import Marks from './Marks.svelte';
  import Status from './Status.svelte';
  import WolfButton from './WolfButton.svelte';
  import PaneOverview from './PaneOverview.svelte';
  import PaneProjects from './PaneProjects.svelte';
  import PaneLink from './PaneLink.svelte';
  import PaneSsh from './PaneSsh.svelte';
  import { rosterUi, type PaneTab } from './roster-ui.svelte';
  import type { RosterComputer } from './roster-model';

  const TABS: readonly PaneTab[] = ['overview', 'projects', 'link', 'ssh'];
  const { c, computers, nowMs, onClose }: { c: RosterComputer; computers: readonly RosterComputer[]; nowMs: number; onClose: () => void } = $props();
  let confirming = $state(false);
  let titleEl = $state<HTMLHeadingElement | undefined>();
  const tabDefs = $derived(TABS.map((id) => ({ id, label: t(`roster.tab.${id}`) })));
  const removable = $derived(!c.isSelf && c.entry !== null);

  $effect(() => {
    void c.id;
    confirming = false;
    void tick().then(() => titleEl?.focus({ preventScroll: true }));
  });

  async function removeIt(): Promise<void> {
    if (!c.entry) return;
    await remove(c.id, c.name);
    confirming = false;
    onClose();
  }
</script>

<header class="m1-pane__head">
  <div class="m1-pane__top">
    <button type="button" class="m1-pane__back" aria-label={t('roster.pane.back')} onclick={onClose}><Icon name="back" size={16} /></button>
    <h2 class="m1-pane__title" tabindex="-1" bind:this={titleEl}>{c.name}</h2>
    <Marks {c} />
    <IconButton label={t('roster.pane.close')} variant="close" icon="close" iconSize={14} data-roster-key="pane-close" onclick={onClose} />
  </div>
  <div class="m1-pane__acts"><Status {c} />
    <span class="m1-pane__btns"><WolfButton {c} />
      {#if removable && !confirming}
        <button type="button" class="oc-btn oc-btn--sm pp-destroy" data-act="remove" disabled={activity.busy !== null} onclick={() => (confirming = true)}>{t('computers.row.remove')}</button>
      {/if}</span></div>
  {#if confirming}
    <div class="pp-confirm" data-open data-act="remove-confirm"><span class="pp-confirm__text">{t('computers.row.remove_confirm', { label: c.name })}</span>
      <span class="pp-confirm__row">
        <button type="button" class="oc-btn oc-btn--sm" onclick={() => (confirming = false)}>{t('computers.row.cancel')}</button>
        <button type="button" class="oc-btn oc-btn--sm pp-destroy" data-act="remove-yes" disabled={activity.busy !== null} onclick={() => void removeIt()}>{t('computers.row.remove')}</button></span></div>
  {/if}
</header>
<Tabs tabs={tabDefs} active={rosterUi.tab} onSelect={(id) => (rosterUi.tab = id as PaneTab)} label={t('roster.pane.tabs')} idBase="roster" class="m1-ptabs" />
<div class="rs-detail-body m1-pane__body" {...panelAttrs('roster', rosterUi.tab)} data-host="">
  {#if rosterUi.tab === 'ssh'}<PaneSsh {c} {computers} {nowMs} />
  {:else if rosterUi.tab === 'link'}<PaneLink {c} />
  {:else if rosterUi.tab === 'projects'}<PaneProjects {c} />
  {:else}<PaneOverview {c} {nowMs} onWork={() => { location.hash = '#pack/work'; }} />{/if}
</div>
