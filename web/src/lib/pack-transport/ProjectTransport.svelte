<script lang="ts" module>
  export type DeckPage = 'home' | 'replicas' | 'github' | 'abilities';
</script>

<script lang="ts">
  import './pack-transport.css';
  import { t } from '../i18n/index.svelte';
  import { nonEmptyErrorMessageOr, withRefusedFiles } from '../errors/failure-reason';
  import Button from '../base/Button.svelte';
  import Switch from '../base/Switch.svelte';
  import State from '../base/State.svelte';
  import Icon from '../../opscenter/ui/Icon.svelte';
  import InfoTip from '../info-tip/InfoTip.svelte';
  import { projects } from '../../opscenter/api/projects.svelte';
  import { packMachines } from '../pack-machines/pack-machines-store.svelte';
  import { stateWords } from '../pack-ssh-targets/ssh-state-words';
  import { loadSshTargets, sshTargets } from '../pack-ssh-targets/ssh-targets-store.svelte';
  import { keyWords } from './abilities-words';
  import ProjectAbilities from './ProjectAbilities.svelte';
  import ProjectAutoDelegate from './ProjectAutoDelegate.svelte';
  import ProjectGithub from './ProjectGithub.svelte';
  import ProjectReplicas from './ProjectReplicas.svelte';
  import { replicasApi, transportApi, type PublishCard, type ReplicasApi, type ReplicasView, type TransportApi, type TransportView } from './transport-api';

  let { name, api = transportApi, repApi = replicasApi, page = $bindable('home') }: { name: string; api?: TransportApi; repApi?: ReplicasApi; page?: DeckPage } = $props();

  let view = $state<TransportView | null>(null);
  let card = $state<PublishCard | null>(null);
  let reps = $state<ReplicasView | null>(null);
  let busy = $state(false);
  let error = $state<string | null>(null);
  let done = $state<string | null>(null);

  const projectName = $derived(name.startsWith('id:') ? ((projects.data ?? []).find((p) => String(p.id) === name.slice(3))?.name ?? '') : name);

  async function load(): Promise<void> {
    try {
      view = await api.read(name);
      card = await api.card(name).catch(() => null);
      error = null;
    } catch (failure) {
      error = nonEmptyErrorMessageOr(failure, t('pack.transport.error.failed'));
    }
    reps = await repApi.list(name).catch(() => null);
  }

  async function change(send: () => Promise<unknown>): Promise<void> {
    if (busy) return;
    busy = true;
    error = null;
    try {
      await send();
    } catch (failure) {
      error = nonEmptyErrorMessageOr(failure, t('pack.transport.error.failed'));
    } finally {
      busy = false;
      await load();
    }
  }

  async function publish(answers: { owner?: string; account?: string }): Promise<void> {
    if (busy || !card) return;
    busy = true;
    error = null;
    done = null;
    let refusal: string | null = null;
    try {
      const made = await api.publish(name, answers);
      done = t('pack.transport.publish_done', { url: made.url });
    } catch (failure) {
      refusal = withRefusedFiles(nonEmptyErrorMessageOr(failure, t('pack.transport.error.failed')), failure, t);
    } finally {
      busy = false;
      await load();
      if (refusal) error = refusal;
    }
  }

  void load();
  void loadSshTargets();

  const others = $derived((packMachines.data?.machines ?? []).filter((m) => m.paired && !m.is_self));
  const capLines = $derived(others.slice(0, 2).map((m) => {
    const can = m.snapshot?.can ?? null;
    const words = can ? keyWords(can).join(', ') : '';
    return `${m.label || m.install_id.slice(0, 8)}: ${m.state === 'connected' && !can ? t('pack.deck.old_tag') : words || t('pack.deck.no_report')}`;
  }));
  const accountDoor = $derived(!view ? '' : view.air_gap ? t('pack.transport.account.air_gap')
    : view.account ? t('pack.transport.account.in_force', { account: view.account, source: t(`pack.transport.source.${view.source}`) }) : t('pack.deck.acct_undecided'));
  const rungDoor = $derived(view ? `${t(`pack.transport.rung.${view.rung}`)}${card?.offered ? `, ${t('pack.deck.publish_offered')}` : ''}` : '');
  const repDoor = $derived(reps && reps.replicas.length > 0 ? t('pack.deck.running_on', { names: reps.replicas.map((r) => r.label).join(', ') }) : t('pack.replicas.none'));

  let seen: number | null | undefined;
  $effect(() => {
    const stamp = projects.fetchedAt;
    if (seen === undefined) { seen = stamp; return; }
    if (stamp !== seen) { seen = stamp; void load(); }
  });

  function key(e: KeyboardEvent): void {
    if (e.key === 'Escape' && page !== 'home') { e.preventDefault(); e.stopPropagation(); page = 'home'; }
  }
</script>

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<div class="dk-body" data-pt="root" data-page={page} onkeydown={key} role="presentation">
  <div class="dk-home" data-home inert={page !== 'home'} data-under={page !== 'home' ? '' : undefined}>
    <div class="dk-col" data-col="work"><ProjectAutoDelegate {name} /></div>
    <div class="dk-col" data-col="doors">
      <Button variant="row" size="bare" data-door="replicas" onclick={() => (page = 'replicas')}>
        <div class="dk-head"><span class="dk-glyph"><Icon name="computers-linked" size={14} /></span><span class="dk-label">{t('pack.replicas.title')}</span><span class="dk-chev"><Icon name="chevron-right" size={12} /></span></div>
        <p class="dk-sum">{repDoor}</p>
      </Button>
      <Button variant="row" size="bare" data-door="github" data-err={error ? '' : undefined} onclick={() => (page = 'github')}>
        <div class="dk-head"><span class="dk-glyph"><Icon name="github" size={14} /></span><span class="dk-label">{t('pack.deck.github')}</span><span class="dk-chev"><Icon name="chevron-right" size={12} /></span></div>
        {#if error}<p class="dk-sum dk-sum--err">{error}</p>{:else if view}<p class="dk-sum">{accountDoor}</p><p class="dk-sum dk-sum--muted">{rungDoor}</p>{:else}<p class="dk-sum">{t('pack.autodelegate.loading')}</p>{/if}
      </Button>
      <Button variant="row" size="bare" data-door="abilities" onclick={() => (page = 'abilities')}>
        <div class="dk-head"><span class="dk-glyph"><Icon name="cpu" size={14} /></span><span class="dk-label">{t('pack.deck.caps_title')}</span><span class="dk-chev"><Icon name="chevron-right" size={12} /></span></div>
        {#each capLines.length ? capLines : [t('pack.autodelegate.no_computers')] as line (line)}<p class="dk-sum">{line}</p>{/each}
      </Button>
    </div>
  </div>
  <div class="dk-foot" data-foot inert={page !== 'home'} data-under={page !== 'home' ? '' : undefined}>
    <div class="dk-grp" data-grp="air-gap">
      <span class="dk-glyph"><Icon name="lock" size={14} /></span><span class="dk-label">{t('pack.transport.air_gap')}</span>
      <InfoTip text={t('pack.transport.air_gap_help')} label={t('pack.transport.info_label')} />
      {#if view}
        <Switch label="" aria-label={t('pack.transport.air_gap')} disabled={busy} data-pt="air-gap" bind:checked={() => view!.air_gap, (next) => void change(() => api.setAirGap(name, next))} />
      {:else if error}<span class="dk-line dk-sum--err">{t('pack.transport.error.failed')}</span>{:else}<span class="dk-line">{t('pack.transport.loading')}</span>{/if}
    </div>
    <div class="dk-grp" data-grp="ssh">
      <span class="dk-label">{t('pack.ssh.rows.title')}</span>
      {#if sshTargets.list.length === 0}<span class="dk-line">{t('pack.deck.none_yet')}</span>
      {:else}
        <span class="dk-ssh">{#each sshTargets.list as target (target.host_key)}<span data-ssh-row={target.host_key} data-s={target.state === 'taking_work' ? 'ok' : 'bad'}><b>{target.label}</b> {stateWords(target, sshTargets.changed[target.host_key] === true)}</span>{/each}</span>
      {/if}
    </div>
  </div>
  {#if page !== 'home'}
    <section class="dk-page" data-page-view={page} aria-label={page === 'abilities' ? t('pack.deck.caps_title') : page === 'github' ? t('pack.deck.github') : t('pack.replicas.title')}>
      <div class="dk-page__body">
        {#if page === 'replicas'}<ProjectReplicas {name} {projectName} api={repApi} onchange={() => void load()} />
        {:else if page === 'github'}
          {#if view}<ProjectGithub {view} {card} {busy} {done} {error} onAccount={(account) => void change(() => api.setAccount(name, account))} onPublish={(a) => void publish(a)} />
          {:else if error}<State kind="error" inline title={error} actionLabel={t('base.state.retry')} onAction={() => void load()} />
          {:else}<State kind="loading" inline title={t('pack.transport.loading')} />{/if}
        {:else}<ProjectAbilities />{/if}
      </div>
    </section>
  {/if}
</div>
