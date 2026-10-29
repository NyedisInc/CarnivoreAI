
<script lang="ts">
  import Button from '../base/Button.svelte';
  import Field from '../base/Field.svelte';
  import Switch from '../base/Switch.svelte';
  import { onMount } from 'svelte';
  import { openModal } from '../modal';
  import { t } from '../i18n/index.svelte';
  import Icon from '../../opscenter/ui/Icon.svelte';
  import IconButton from '../base/IconButton.svelte';
  import FedConfirmModal from '../hosts-page/FedConfirmModal.svelte';
  import ShowCodeModal from '../hosts-page/ShowCodeModal.svelte';
  import RosterJoin from './RosterJoin.svelte';
  import { createFederationApi, errorCode, readPackName, writePackName } from '../hosts-page/federation-api';
  import { ageWords, stateWords } from '../computers/computers-format';
  import { activity, computers, leave } from '../computers/computers-store.svelte';
    import { reasonOf } from './roster-store.svelte';

  const { onClose, nowMs }: { onClose: () => void; nowMs: number } = $props();
  const fed = createFederationApi();
  const view = $derived(computers.data);
  const role = $derived(view?.self.role ?? 'standalone');
  const main = $derived(view?.self.main ?? null);
  const mainName = $derived(main?.label ?? t('computers.join.main_fallback'));
  const linkState = $derived(view?.self.link.state ?? null);
  let advertise = $state<boolean | null>(null);
  let problem = $state<string | null>(null);
  let nameValue = $state('');
  let nameSaved = $state('');
  let nameBusy = $state(false);
  let titleEl = $state<HTMLHeadingElement | undefined>();

  onMount(() => {
    void readPackName().then((n) => { nameValue = nameSaved = n ?? ''; }).catch(() => { problem = t('computers.pack_name.failed'); });
    void fed.settings().then((s) => { advertise = s.advertise; }).catch(() => { advertise = null; });
    titleEl?.focus({ preventScroll: true });
  });

  async function toggleAdvertise(next: boolean): Promise<void> {
    problem = null;
    try { advertise = (await fed.setAdvertise(next)).advertise; } catch (e) { problem = reasonOf(e); }
  }

  async function saveName(event: Event): Promise<void> {
    event.preventDefault();
    if (nameBusy) return;
    nameBusy = true;
    problem = null;
    try { const n = await writePackName(nameValue.trim() === '' ? null : nameValue.trim()); nameValue = nameSaved = n ?? ''; }
    catch (e) { problem = errorCode(e) === 'bad_pack_name' ? t('computers.pack_name.bad') : t('computers.pack_name.failed'); }
    finally { nameBusy = false; }
  }

  async function leavePack(): Promise<void> {
    const yes = await openModal<true, { title: string; body: string; confirmLabel: string }>(FedConfirmModal, {
      title: t('computers.member.leave'), body: t('computers.member.leave_confirm', { main: mainName }), confirmLabel: t('computers.member.leave'),
    });
    if (yes) await leave();
  }

  async function rotate(): Promise<void> {
    const yes = await openModal<true, { title: string; body: string; confirmLabel: string }>(FedConfirmModal, {
      title: t('hosts.rotate.title'), body: t('hosts.rotate.body'), confirmLabel: t('hosts.rotate.confirm'),
    });
    if (!yes) return;
    problem = null;
    try { await fed.rotate(); } catch (e) { problem = reasonOf(e); }
  }
</script>

<aside class="m1-sets" aria-label={t('roster.sets.title')} data-panel="settings">
  <header class="m1-pane__head"><div class="m1-pane__top">
    <span class="m1-sets__ico" aria-hidden="true"><Icon name="gear" size={14} /></span>
    <h2 class="m1-pane__title" tabindex="-1" bind:this={titleEl}>{t('roster.sets.title')}</h2>
    <IconButton label={t('roster.sets.close')} variant="close" icon="close" iconSize={14} data-roster-key="sets-close" onclick={onClose} />
  </div></header>
  <div class="rs-detail-body m1-pane__body">
    <section class="m1-sec" data-sec="name">
      <form class="pp-form pp-name" data-cmp="pack-name" onsubmit={saveName}>
        <div class="pp-fieldrow"><Field block type="text" maxlength={32} autocomplete="off" autocapitalize="off" spellcheck="false" bind:value={nameValue}
          aria-label={t('roster.sets.name_placeholder')} placeholder={t('roster.sets.name_placeholder')} data-cmp="pack-name-input" /></div>
        <div class="pp-acts"><Button type="submit" variant="confirm" data-cmp="pack-name-save" disabled={nameBusy || nameValue.trim() === nameSaved}>{t('roster.sets.name_save')}</Button></div>
      </form>
    </section>
    <section class="m1-sec"><h3 class="pp-k">{t('roster.sets.network')}</h3>
      {#if advertise !== null}
        <div class="pp-swrow"><span class="pp-swrow__label">{t('roster.sets.advertise')}</span>
          <Switch bare label="" bind:checked={() => advertise === true, (next) => void toggleAdvertise(next)} aria-label={t('roster.sets.advertise')} data-act="advertise" /></div>
      {/if}
      {#if linkState === 'port_busy'}<p class="pp-warn">{t('roster.sets.link_port_busy')}</p>
      {:else if linkState === 'off_loopback'}<p class="pp-warn">{t('computers.link.off_loopback')}</p>
      {:else if linkState === 'local_network_blocked'}<p class="pp-warn">{t('computers.link.local_network_blocked')}</p>{/if}
      <p class="pp-hint">{t('computers.footer.awake')}</p>
    </section>
    {#if role === 'member'}
      <section class="m1-sec" data-sec="membership"><h3 class="pp-k">{t('roster.sets.membership')}</h3>
        <div class="pp-member" data-cmp="member-line">
          <p class="pp-member__line"><b>{t('roster.sets.joined', { name: nameSaved || t('roster.sets.pack_of', { main: mainName }) })}</b>
            {#if main}<span class="pp-st" data-shape={main.state === 'connected' ? 'filled' : 'hollow'} data-tone={main.state === 'connected' ? 'ok' : 'warn'}><i class="pp-st__mark"></i><span class="pp-st__word">{stateWords(main.state)}</span></span>
            <span class="pp-dim">{t('roster.sets.last_seen', { age: ageWords(main.last_link_at, nowMs) })}</span>{/if}</p>
          {#if main?.reachable_note}<p class="pp-warn">{t('computers.member.unreachable_hours')}</p>{/if}
          <div class="pp-acts"><Button variant="danger" size="sm" data-act="leave" disabled={activity.busy !== null} onclick={() => void leavePack()}>{t('computers.member.leave')}</Button></div>
        </div>
      </section>
    {:else}
      <RosterJoin />
    {/if}
    <section class="m1-sec"><h3 class="pp-k">{t('roster.sets.code')}</h3>
      <p class="pp-hint">{t('roster.sets.code_note')}</p>
      <div class="pp-acts"><Button data-act="show-code" onclick={() => void openModal(ShowCodeModal, {})}>{t('roster.sets.code_button')}</Button></div>
    </section>
    {#if problem}<p class="pp-err" role="alert">{problem}</p>{/if}
    <div class="m1-danger"><h3 class="pp-k m1-danger__k">{t('roster.sets.danger')}</h3>
      <p class="pp-hint">{t('roster.sets.rotate_note')}</p>
      <div class="pp-acts"><Button variant="danger" size="sm" data-act="rotate" onclick={() => void rotate()}>{t('roster.sets.rotate')}</Button></div></div>
  </div>
</aside>
