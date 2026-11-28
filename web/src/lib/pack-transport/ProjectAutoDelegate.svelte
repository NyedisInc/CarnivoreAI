<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import { nonEmptyErrorMessageOr } from '../errors/failure-reason';
  import { codedSentence } from '../../opscenter/api/auth.svelte';
  import { projects } from '../../opscenter/api/projects.svelte';
  import { ageWords } from '../computers/computers-format';
  import Button from '../base/Button.svelte';
  import Checkbox from '../base/Checkbox.svelte';
  import IconButton from '../base/IconButton.svelte';
  import List from '../base/List.svelte';
  import ListRow from '../base/ListRow.svelte';
  import State from '../base/State.svelte';
  import Switch from '../base/Switch.svelte';
  import Tag from '../base/Tag.svelte';
  import Icon from '../../opscenter/ui/Icon.svelte';
  import InfoTip from '../info-tip/InfoTip.svelte';
  import { packMachines, type PackMachine } from '../pack-machines/pack-machines-store.svelte';
  import { autoDelegateApi, type AutoDelegateApi, type AutoDelegateBody, type AutoDelegateView, type RecentJob } from './auto-delegate-api';
  import { hintFor, isOld, isTicked } from './delegate-rows';
  import { reasonFor } from './leftover-codes';
  import { meshOn } from '../pack-roster/roster-model';

  const MESH_REFUSALS: readonly string[] = ['not_linked', 'on_demand_only', 'older_app', 'no_status_card', 'member_list_unreadable', 'own_link_off', 'member_not_listed', 'member_not_mesh', 'member_link_off'];

  let { name, api = autoDelegateApi }: { name: string; api?: AutoDelegateApi } = $props();

  let view = $state<AutoDelegateView | null>(null);
  let jobs = $state<RecentJob[]>([]);
  let busy = $state(false);
  let error = $state<string | null>(null);
  let notes = $state<string[]>([]);
  let more = $state(false);

  const on = $derived(view?.auto_delegate === true);
  const never = $derived(view?.never_use ?? []);
  const copies = $derived(view?.copies ?? []);
  const computers = $derived((packMachines.data?.machines ?? []).filter((m) => m.paired && !m.is_self));
  const shown = $derived(computers.length > 5 && !more ? computers.slice(0, 4) : computers);
  const takesWork = (m: PackMachine): boolean => m.snapshot?.restrictions.may_host_agents !== false && !(view?.no_work ?? []).includes(m.install_id);
  const copyOf = (m: PackMachine) => copies.find((c) => c.install_id === m.install_id);
  const leftovers = $derived(on ? [] : copies.filter((c) => c.auto));
  const running = $derived(view?.copy_run?.running === true);
  const mesh = $derived(meshOn(packMachines.data));
  const reason = (code: string): string => (mesh && MESH_REFUSALS.includes(code) ? t(`pack.autodelegate.refused.${code}`) : codedSentence({ code }, ''));
  const memberRefused = $derived(mesh && view?.role === 'home'
    ? Object.entries(view.copy_run?.refused ?? {}).filter(([id]) => !computers.some((m) => m.install_id === id || m.label === id))
      .map(([id, code]): [string, string, string] => [packMachines.data?.machines.find((m) => m.install_id === id)?.label || id.slice(0, 8), reason(code), id])
    : []);
  const targets = $derived(computers.filter((m) => m.state === 'connected' && !isOld(m) && takesWork(m) && isTicked(m, never) && !copyOf(m)));
  const jobsRunning = $derived(on && (view?.live_jobs ?? 0) > 0);
  const notRepo = $derived(view?.is_repo === false && !on);
  const names = $derived(targets.length === 1 ? targets[0]!.label : targets.length === 2 ? `${targets[0]!.label} and ${targets[1]!.label}` : '');
  const nameWords = $derived(names && names.length <= 24 ? names : t(targets.length === 1 ? 'pack.deck.computer_one' : 'pack.deck.computer_many', { n: String(targets.length) }));

  /* there is nothing */
  function hint(m: PackMachine): string {
    const run = view?.copy_run;
    const refused = run?.refused?.[m.install_id] ?? run?.refused?.[m.label] ?? null;
    return hintFor(m, { never: !isTicked(m, never) && !isOld(m), hasCopy: !!copyOf(m), takesWork: takesWork(m), refused, copying: on && running && !copyOf(m) }, t,
      reason);
  }

  async function load(): Promise<void> {
    try {
      view = await api.get(name);
      error = null;
      jobs = view.project_uid && view.auto_delegate ? await api.recentJobs(view.project_uid).catch(() => []) : [];
    } catch (failure) {
      error = nonEmptyErrorMessageOr(failure, t('pack.autodelegate.error.failed'));
    }
  }

  async function write(body: AutoDelegateBody): Promise<AutoDelegateView | null> {
    if (busy) return null;
    busy = true;
    error = null;
    notes = [];
    try {
      view = await api.put(name, body);
      return view;
    } catch (failure) {
      error = nonEmptyErrorMessageOr(failure, t('pack.autodelegate.error.failed'));
      return null;
    } finally {
      busy = false;
    }
  }

  async function trash(ids: string[]): Promise<void> {
    const answer = await write({ on: false, delete_copies: true, delete_only: ids });
    if (!answer) return;
    notes = [
      ...(answer.deleted ?? []).filter((d) => d.code).map((d) => reasonFor(d.code)),
      ...(answer.kept ?? []).map((k) => t('pack.autodelegate.leftover.kept', { computer: k.label, reason: reasonFor(k.code) })),
    ];
  }

  function tick(m: PackMachine, ticked: boolean): void {
    const rest = never.filter((e) => e !== m.install_id && e !== m.label);
    void write({ on, never_use: ticked ? rest : [...rest, m.install_id] });
  }

  const jobWords = (j: RecentJob): string => `${j.kind || j.task_head || t('pack.deck.job')} ${t('pack.deck.job_on', { computer: j.computer ?? '' })}`;

  void load();

  let seen: number | null | undefined;
  $effect(() => {
    const stamp = projects.fetchedAt;
    if (seen === undefined) { seen = stamp; return; }
    if (stamp !== seen) { seen = stamp; void load(); }
  });
</script>

<div class="dk-tile" data-tile="auto-delegate" data-pt="autodelegate" data-err={error ? '' : undefined}>
  <div class="dk-head">
    <span class="dk-glyph dk-glyph--coral"><Icon name="wolf" size={14} /></span>
    <span class="dk-label">{t('pack.autodelegate.title')}</span>
    <InfoTip text={t(on ? 'pack.autodelegate.hint_on' : 'pack.autodelegate.hint_off')} label={t('pack.transport.info_label')} />
    {#if view?.role === 'home'}
      <span class="dk-end">
        <span class="dk-line">{t(on ? 'pack.deck.on' : 'pack.deck.off')}</span>
        <Switch label="" aria-label={t('pack.autodelegate.switch')} bind:checked={() => on, (next) => void write({ on: next })} disabled={busy || notRepo || jobsRunning} data-ad="switch" />
      </span>
    {/if}
  </div>
  <div class="dk-desc dk-desc--tile"><p>{t('pack.deck.auto_one')}</p></div>
  {#if error}<State kind="error" inline title={error} data-ad="error" />{/if}
  {#if !view}
    {#if !error}<State kind="loading" inline title={t('pack.autodelegate.loading')} data-ad="loading" />{/if}
  {:else if view.role === 'copy'}
    <p class="dk-sum" data-ad="copy-here">{t('pack.autodelegate.copy_here', { computer: view.home_computer ?? '' })}</p>
  {:else if view.role === 'moved'}
    <p class="dk-sum" data-ad="moved">{t('pack.autodelegate.moved', { computer: view.moved_to ?? '' })}</p>
  {:else}
    {#if notRepo}<State kind="warn" inline title={t('pack.autodelegate.not_repo')} data-ad="not-repo" />{/if}
    {#if jobsRunning}<State kind="warn" inline title={t('pack.autodelegate.jobs_running')} data-ad="jobs-running" />{/if}
    <p class="dk-sum">{t(on ? 'pack.deck.sum_on' : 'pack.deck.sum_off')}</p>
    {#if !notRepo}
      <h4 class="oc-sub">{t('pack.autodelegate.computers')}{#if computers.length} <span class="dk-count">{computers.length}</span>{/if}</h4>
      {#if computers.length === 0}
        <State kind="empty" inline title={t('pack.autodelegate.no_computers')} data-ad="no-computers" />
      {:else}
        <List label={t('pack.autodelegate.computers')}>
          {#each shown as m (m.install_id)}
            {@const label = m.label || m.install_id.slice(0, 8)}
            <ListRow class="dk-tick" data-computer={m.install_id} primary={label} secondary={hint(m)}>
              {#snippet lead()}<Checkbox aria-label={label} disabled={busy || isOld(m)} bind:checked={() => isTicked(m, never), (next) => tick(m, next)} data-ad="computer" />{/snippet}
            </ListRow>
          {/each}
        </List>
        {#if computers.length > 5}
          <div class="dk-more">
            <Button size="sm" data-ad="more" onclick={() => (more = !more)}>
              <Icon name={more ? 'chevron-up' : 'chevron-down'} size={12} />{more ? t('pack.deck.fewer') : t('pack.deck.more', { n: String(computers.length - 4) })}</Button>
          </div>
        {/if}
      {/if}
      {#each memberRefused as [computer, words, rid] (rid)}
        <State kind="warn" inline data-ad="member-refused" title={words ? t('pack.autodelegate.member_refused', { computer, reason: words }) : t('pack.autodelegate.member_refused_generic', { computer })} />
      {/each}
      {#if on && computers.length && jobs.length}
        <h4 class="oc-sub">{t('pack.deck.recent')}</h4>
        <ul class="dk-jobs" data-ad="jobs">
          {#each jobs as j (j.id)}<li><b>{jobWords(j)}</b><span>{ageWords(new Date(j.created_at * 1000).toISOString(), Date.now())}</span></li>{/each}
        </ul>
      {/if}
      {#if on && !jobsRunning && (targets.length > 0 || running)}
        <div class="dk-acts dk-acts--copy">
          <Button variant="secondary" disabled={busy || running} data-ad="copy-now" onclick={() => void write({ on: true })}>
            <Icon name="copy" size={12} />{t(running ? 'pack.deck.copying_to' : 'pack.deck.copy_to', { names: nameWords })}</Button>
          <span class="dk-line" data-copy-line>{t('pack.deck.copy_line', { names: nameWords })}</span>
        </div>
      {/if}
    {/if}
  {/if}
</div>

{#if view?.role === 'home' && !on && (leftovers.length > 0 || notes.length > 0)}
  <div class="dk-tile dk-tile--leftover" data-tile="leftover">
    <div class="dk-head">
      <span class="dk-glyph dk-glyph--coral"><Icon name="trash" size={14} /></span>
      <span class="dk-label">{t('pack.autodelegate.leftover.title')}</span>
      <span class="dk-count">{leftovers.length}</span>
      {#if leftovers.length >= 2}
        <span class="dk-end">
          <Button variant="danger" size="sm" disabled={busy} data-ad="trash-all" aria-label={t('pack.deck.trash_all_aria')}
            onclick={() => void trash(leftovers.map((c) => c.install_id))}><Icon name="trash" size={12} />{t('pack.deck.trash_all')}</Button>
        </span>
      {/if}
    </div>
    {#if leftovers.length > 0}
      <List label={t('pack.autodelegate.leftover.title')}>
        {#each leftovers as c (c.install_id)}
          {@const computer = c.label || c.install_id}
          <ListRow wrap data-ad="leftover" data-computer={c.install_id} primary={computer} secondary={c.root ?? ''}>
            {#snippet lead()}<Tag tone="warn">{t('pack.autodelegate.leftover.tag')}</Tag>{/snippet}
            {#snippet actions()}
              <IconButton icon="trash" iconSize={14} variant="danger" label={t('pack.autodelegate.leftover.trash_aria', { computer })} disabled={busy} data-ad="leftover-trash" onclick={() => void trash([c.install_id])} />
            {/snippet}
          </ListRow>
        {/each}
      </List>
    {/if}
    {#each notes as line (line)}<State kind="warn" inline title={line} data-ad="note" />{/each}
  </div>
{/if}
