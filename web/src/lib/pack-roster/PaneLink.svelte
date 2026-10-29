
<script lang="ts">
  import { openModal } from '../modal';
  import { t } from '../i18n/index.svelte';
  import Check from '../../opscenter/ui/Check.svelte';
  import FedConfirmModal from '../hosts-page/FedConfirmModal.svelte';
  import { createFederationApi, type GrantRow } from '../hosts-page/federation-api';
  import { peerStateHelp, peerStateLabel } from './link-words';
  import { setDirection, activity } from '../computers/computers-store.svelte';
  import { loginOf, type RosterComputer } from './roster-model';
  import { reasonOf, refreshRoster } from './roster-store.svelte';

  const { c }: { c: RosterComputer } = $props();
  const fed = createFederationApi();
  let grants = $state<readonly GrantRow[] | null>(null);
  let problem = $state<string | null>(null);
  const peer = $derived(c.peer);

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

{#if c.isSelf}
  <p class="pp-hint">{t('roster.link.self_note')} {t('computers.footer.awake')}</p>
{:else if !peer}
  <p class="pp-hint">{t('roster.link.none')}</p>
{:else}
  <section class="m1-sec" data-act="link">
    <dl class="pp-facts">
      <dt>{t('roster.link.state')}</dt><dd>{peerStateLabel(peer.state, t)}</dd>
      <dt>{t('roster.link.key')}</dt><dd>{c.entry?.fid_short ?? peer.fid.slice(0, 8)}</dd>
      <dt>{t('roster.link.protocol')}</dt><dd>{peer.protocol ?? '-'}</dd>
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
  <section class="m1-sec"><h3 class="pp-k">{t('roster.link.grants')}</h3>
    {#if grants === null}<span class="pp-dim">-</span>
    {:else if grants.length === 0}<p class="pp-hint">{t('roster.link.no_grants')}</p>
    {:else}
      <ul class="pp-grants">
        {#each grants as g (g.grant_id)}
          <li class="pp-swrow"><span>{g.label} <span class="pp-dim">{g.revoked_at ? t('roster.link.revoked') : g.scopes.join(', ')}</span></span>
            {#if !g.revoked_at}<button type="button" class="oc-btn oc-btn--sm" data-grant={g.grant_id}
              onclick={() => void act(t('roster.link.revoke_body', { name: c.name }), t('roster.link.revoke'), () => fed.revoke(g.grant_id))}>{t('roster.link.revoke')}</button>{/if}</li>
        {/each}
      </ul>
    {/if}
  </section>
  {#if problem}<p class="pp-err" role="alert">{problem}</p>{/if}
  <div class="m1-danger"><h3 class="pp-k m1-danger__k">{t('roster.link.danger')}</h3>
    <button type="button" class="oc-btn pp-destroy" data-act="unpair"
      onclick={() => void act(t('roster.link.unpair_body', { name: c.name }), t('roster.link.unpair'), () => fed.unpair(peer.key))}>{t('roster.link.unpair')}</button></div>
{/if}
