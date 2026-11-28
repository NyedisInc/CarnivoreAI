
<script lang="ts">
  import Button from '../base/Button.svelte';
  import { openModal } from '../modal';
  import { t } from '../i18n/index.svelte';
  import Check from '../../opscenter/ui/Check.svelte';
  import FedConfirmModal from '../hosts-page/FedConfirmModal.svelte';
  import { ageWords } from '../computers/computers-format';
  import { createFederationApi, type GrantRow } from '../hosts-page/federation-api';
  import { peerStateHelp, peerStateLabel } from './link-words';
  import { setDirection, activity } from '../computers/computers-store.svelte';
  import { packMachines } from '../pack-machines/pack-machines-store.svelte';
  import { loginOf, meshOn, orderEditable, type RosterComputer } from './roster-model';
  import { reconnectActivity, setLinkPeers } from './reconnect-store.svelte';
  import { reasonOf, refreshRoster } from './roster-store.svelte';

  const { c }: { c: RosterComputer } = $props();
  const fed = createFederationApi();
  let grants = $state<readonly GrantRow[] | null>(null);
  let problem = $state<string | null>(null);
  const peer = $derived(c.peer);
  const view = $derived(packMachines.data);
  const linkOn = $derived(c.machine?.link_peers);
  const linkEditable = $derived(orderEditable(view));
  const unknown = $derived(meshOn(view) && view?.link_switches_unknown === true && linkEditable && c.machine !== null);
  const scopeLabel = (scope: string): string => { const key = `roster.scope.${scope}`; const word = t(key); return word === key ? scope : word; };
  const showLink = $derived(meshOn(view) && !c.isSelf && !c.isAlpha && (typeof linkOn === 'boolean' || unknown));
  let linkProblem = $state<string | null>(null);

  async function flipLink(next: boolean): Promise<void> {
    if (unknown) {
      const yes = await openModal<true, { title: string; body: string; confirmLabel: string }>(FedConfirmModal, { title: t('roster.mesh.switch.title'), body: t('roster.mesh.switch.unknown_confirm', { name: c.name }), confirmLabel: t('roster.mesh.switch.unknown_go') });
      if (!yes) return;
    }
    linkProblem = (await setLinkPeers(c.id, next)) ? null : reconnectActivity.error;
  }

  $effect(() => {
    const iid = c.id;
    grants = null;
    if (c.isSelf || !peer) return;
    void fed.grants().then((all) => { if (c.id === iid) grants = all.filter((g) => g.peer_install_id === iid); }).catch((e: unknown) => { grants = []; problem = reasonOf(e); });
  });

  async function act(body: string, label: string, run: () => Promise<unknown>): Promise<void> {
    const yes = await openModal<true, { title: string; body: string; confirmLabel: string }>(FedConfirmModal, { title: label, body, confirmLabel: label });
    if (!yes) return;
    problem = null;
    try { await run(); } catch (e) { problem = reasonOf(e); }
    await refreshRoster();
    if (peer && !c.isSelf) grants = (await fed.grants().catch(() => [])).filter((g) => g.peer_install_id === c.id);
  }
</script>

{#snippet linkSwitch()}
  {#if showLink}
    <section class="m1-sec" data-sec="link-peers"><h3 class="pp-k">{t('roster.mesh.switch.title')}</h3>
      {#if unknown}<p class="pp-warn" data-line="link-peers-unknown">{t('roster.mesh.switch.unknown', { name: c.name })}</p>{/if}
      <Check label={t('roster.mesh.switch.label', { name: c.name })} checked={linkOn === true} role="switch" disabled={!linkEditable || reconnectActivity.busy !== null}
        data-cmp="link-peers" onToggle={(next) => void flipLink(next)} />
      {#if !linkEditable}<p class="pp-hint" data-line="link-peers-readonly">{view?.interim === true ? t('roster.mesh.switch.frozen') : t('roster.mesh.switch.readonly')}</p>{/if}
      {#if c.machine?.mesh_capable === false}<p class="pp-hint" data-line="link-peers-update">{t('roster.mesh.switch.needs_update', { name: c.name })}</p>{/if}
      {#if linkProblem}<p class="pp-err" role="alert">{linkProblem}</p>{/if}
    </section>
  {/if}
{/snippet}

{#if c.isSelf}
  <p class="pp-hint">{t('roster.link.self_note')} {t('computers.footer.awake')}</p>
{:else if !peer && c.mesh}
  <section class="m1-sec" data-act="mesh-link">
    <dl class="pp-facts">
      <dt>{t('roster.link.state')}</dt><dd>{t(`roster.dial.${c.dial}`)}</dd>
      <dt>{t('roster.mesh.since')}</dt><dd>{ageWords(c.since, Date.now())}</dd>
      <dt>{t('roster.link.dialled_by')}</dt><dd>{c.mesh.dialed_by === 'this' ? t('roster.link.dialled_this') : c.mesh.dialed_by === 'peer' ? t('roster.link.dialled_them') : '-'}</dd>
      <dt>{t('roster.mesh.held')}</dt><dd>{c.mesh.standing ? t('roster.mesh.kind_standing') : c.mesh.on_demand ? t('roster.mesh.kind_on_demand') : t('roster.mesh.kind_none')}</dd>
    </dl>
  </section>
  {@render linkSwitch()}
{:else if !peer}
  <p class="pp-hint">{t('roster.link.none')}</p>
  {@render linkSwitch()}
{:else}
  <section class="m1-sec" data-act="link">
    <dl class="pp-facts">
      <dt>{t('roster.link.state')}</dt><dd>{peerStateLabel(peer.state, t)}</dd>
      <dt>{t('roster.link.key')}</dt><dd>{c.entry?.fid_short ?? peer.fid.slice(0, 8)}</dd>
      {#if c.transport}<dt>{t('roster.link.protocol')}</dt><dd>{c.transport}</dd>{/if}
      {#if c.machine?.link_path && c.machine.link_path !== 'none'}<dt>{t('roster.link.path')}</dt>
        <dd>{c.viaRelay ? t('roster.reconnect.via_relay') : t('roster.link.path_direct')}{#if c.machine.relay_id_known === false}{' '}<span class="pp-dim">{t('roster.reconnect.relay_unknown')}</span>{/if}</dd>{/if}
      <dt>{t('roster.link.dialled_by')}</dt><dd>{peer.initiator ? t('roster.link.dialled_this') : t('roster.link.dialled_them')}</dd>
      {#if c.host}<dt>{t('roster.link.ssh_target')}</dt><dd>{loginOf(c.host)}</dd>{/if}
    </dl>
    <p class="pp-hint">{peerStateHelp(peer.state, t)}</p>
  </section>
  {#if c.entry}
    <section class="m1-sec"><h3 class="pp-k">{t('roster.link.control')}</h3>
      <Check label={t('computers.row.control', { label: c.entry.label })} checked={c.entry.direction !== 'one_way'} role="switch" disabled={activity.busy !== null}
        data-cmp="direction" onToggle={(next) => void setDirection(c.entry!.install_id, next)} />
    </section>
  {/if}
  {@render linkSwitch()}
  <section class="m1-sec"><h3 class="pp-k">{t('roster.link.grants')}</h3>
    {#if grants === null}<span class="pp-dim">-</span>
    {:else if grants.length === 0}<p class="pp-hint">{t('roster.link.no_grants')}</p>
    {:else}
      <ul class="pp-grants">
        {#each grants as g (g.grant_id)}
          <li class="pp-swrow"><span>{g.label} <span class="pp-dim">{g.revoked_at ? t('roster.link.revoked') : g.scopes.map(scopeLabel).join(', ')}</span></span>
            {#if !g.revoked_at}<Button variant="danger" size="sm" data-grant={g.grant_id}
              onclick={() => void act(t('roster.link.revoke_body', { name: c.name }), t('roster.link.revoke'), () => fed.revoke(g.grant_id))}>{t('roster.link.revoke')}</Button>{/if}</li>
        {/each}
      </ul>
    {/if}
  </section>
  {#if problem}<p class="pp-err" role="alert">{problem}</p>{/if}
  <div class="m1-danger"><h3 class="pp-k m1-danger__k">{t('roster.link.danger')}</h3>
    <Button variant="danger" data-act="unpair"
      onclick={() => void act(t('roster.link.unpair_body', { name: c.name }), t('roster.link.unpair'), () => fed.unpair(peer.key))}>{t('roster.link.unpair')}</Button></div>
{/if}
