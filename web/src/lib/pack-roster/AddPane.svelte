
<script lang="ts">
  import { openModal } from '../modal';
  import { t } from '../i18n/index.svelte';
  import IconButton from '../base/IconButton.svelte';
  import Button from '../base/Button.svelte';
  import Segmented from '../base/Segmented.svelte';
  import AddHostModal from '../hosts-page/AddHostModal.svelte';
  import PairModal from '../hosts-page/PairModal.svelte';
  import AddOverSsh from '../computers/AddOverSsh.svelte';
  import InviteCard from '../computers/InviteCard.svelte';
  import { activity, addComputer } from '../computers/computers-store.svelte';
  import { createFederationApi, type DiscoveredMac, type PeerRow } from '../hosts-page/federation-api';
  import { refreshRoster } from './roster-store.svelte';
  import { rosterUi } from './roster-ui.svelte';

  const ROUTES = ['code', 'ssh', 'host', 'older'] as const;
  const { onClose, found = null }: { onClose: () => void; found?: DiscoveredMac | null } = $props();
  const fed = createFederationApi();
  const routeOptions = $derived(ROUTES.map((route) => ({ value: route, label: t(`roster.add.route.${route}`), attrs: { 'data-route': route } })));

  async function addHost(): Promise<void> {
    if (await openModal(AddHostModal, {})) await refreshRoster();
  }

  async function pair(): Promise<void> {
    const peer = await openModal<PeerRow, { fed: ReturnType<typeof createFederationApi>; found: DiscoveredMac | null }>(PairModal, { fed, found });
    if (peer) await refreshRoster();
  }
</script>

<header class="m1-pane__head"><div class="m1-pane__top">
  <IconButton label={t('roster.pane.back')} variant="quiet" icon="back" iconSize={16} data-roster-key="pane-back" onclick={onClose} />
  <h2 class="m1-pane__title" tabindex="-1">{t('roster.add.title')}</h2>
  <IconButton label={t('roster.pane.close')} variant="close" icon="close" iconSize={14} data-roster-key="pane-close" onclick={onClose} />
</div></header>
<div class="rs-detail-body m1-pane__body">
  <div class="rs-routes">
    <Segmented label={t('roster.add.routes')} options={routeOptions} value={rosterUi.route} onchange={(v) => (rosterUi.route = v as (typeof ROUTES)[number])} />
  </div>
  {#if rosterUi.route === 'code'}
    <div class="pp-acts"><Button variant="confirm" data-cmp="add" disabled={activity.busy !== null} onclick={() => void addComputer()}>{t('computers.add')}</Button></div>
    <InviteCard />
  {:else if rosterUi.route === 'ssh'}
    <AddOverSsh prefill={rosterUi.prefillLogin} />
  {:else if rosterUi.route === 'host'}
    <p class="pp-hint">{t('roster.add.host_note')}</p>
    <div class="pp-acts"><Button variant="confirm" data-act="open-host" onclick={() => void addHost()}>{t('roster.add.open')}</Button></div>
  {:else}
    <p class="pp-hint">{t('roster.add.older_note')}</p>
    <div class="pp-acts"><Button variant="confirm" data-act="open-pair" onclick={() => void pair()}>{t('roster.add.open')}</Button></div>
  {/if}
</div>
