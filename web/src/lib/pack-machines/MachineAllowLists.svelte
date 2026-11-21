<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import { nonEmptyErrorMessageOr } from '../errors/failure-reason';
  import Button from '../base/Button.svelte';
  import Checkbox from '../base/Checkbox.svelte';
  import Segmented from '../base/Segmented.svelte';
  import { packActivity, saveRestrictions, type PackMachine } from './pack-machines-store.svelte';
  import { allowApi, type AllowApi, type AllowChoices } from './allow-api';

  let { machine, api = allowApi }: { machine: PackMachine; api?: AllowApi } = $props();

  const storedProjects: string[] = [...(machine.snapshot?.restrictions.allowed_projects ?? [])];
  const storedCompanies: string[] = [...(machine.snapshot?.restrictions.allowed_companies ?? [])];
  const isPeer = !machine.is_self;

  let choices = $state<AllowChoices | null>(null);
  let error = $state<string | null>(null);
  let mode = $state<'every' | 'only'>(storedProjects.length + storedCompanies.length > 0 ? 'only' : 'every');
  let projectsOn = $state<string[]>(storedProjects.slice());
  let companiesOn = $state<string[]>(storedCompanies.slice());

  const knownProjects = $derived(new Set((choices?.projects ?? []).map((p) => p.uid)));
  const knownCompanies = $derived(new Set((choices?.companies ?? []).map((c) => c.uid)));
  const unknownProjects = $derived(choices ? storedProjects.filter((u) => !knownProjects.has(u)) : []);
  const unknownCompanies = $derived(choices ? storedCompanies.filter((u) => !knownCompanies.has(u)) : []);
  const keptProjects = $derived(projectsOn.filter((u) => !unknownProjects.includes(u)));

  const nextProjects = $derived(mode === 'every' ? [] : [...new Set([...projectsOn, ...unknownProjects])]);
  const nextCompanies = $derived(mode === 'every' ? [] : [...new Set([...companiesOn, ...unknownCompanies])]);
  const same = (a: string[], b: string[]): boolean => a.length === b.length && a.every((u) => b.includes(u));
  const changed = $derived(!same(nextProjects, storedProjects) || !same(nextCompanies, storedCompanies));
  const nothingTicked = $derived(mode === 'only' && nextProjects.length + nextCompanies.length === 0);
  const widens = $derived(isPeer && ((storedProjects.length > 0 && (nextProjects.length === 0 || !nextProjects.every((u) => storedProjects.includes(u))))
    || (storedCompanies.length > 0 && (nextCompanies.length === 0 || !nextCompanies.every((u) => storedCompanies.includes(u))))));
  const reason = $derived(nothingTicked ? t('pack.allow.nothing_ticked') : widens ? t('pack.allow.peer_widen') : '');
  const busy = $derived(packActivity.busy !== null);

  const locked = (uid: string, stored: string[]): boolean => isPeer && stored.length > 0 && !stored.includes(uid);
  const hintFor = (uid: string, stored: string[]): string | undefined => (locked(uid, stored) ? t('pack.allow.peer_locked') : undefined);

  const toggled = (list: string[], uid: string, on: boolean): string[] => (on ? [...new Set([...list, uid])] : list.filter((u) => u !== uid));

  function save(): void {
    void saveRestrictions(machine.install_id, { allowed_projects: nextProjects, allowed_companies: nextCompanies });
  }

  async function load(): Promise<void> {
    try {
      choices = await api.get();
    } catch (failure) {
      error = nonEmptyErrorMessageOr(failure, t('pack.allow.error'));
    }
  }
  void load();
</script>

<div class="pm-reserve" data-pm="allow-lists">
  <h3 class="pl-label">{t('pack.allow.title')}</h3>
  <Segmented label={t('pack.allow.title')} bind:value={() => mode, (v) => (mode = v === 'only' ? 'only' : 'every')} disabled={busy}
    options={[
      { value: 'every', label: t('pack.allow.every'), disabled: isPeer && storedProjects.length + storedCompanies.length > 0, attrs: { 'data-allow': 'every' } },
      { value: 'only', label: t('pack.allow.only'), attrs: { 'data-allow': 'only' } },
    ]} />
  {#if error}<p class="pm-error" role="alert" data-allow="error">{error}</p>{/if}
  {#if mode === 'only'}
    {#if !choices && !error}
      <p class="pm-note" data-allow="loading">{t('pack.allow.loading')}</p>
    {:else if choices}
      {#if choices.companies.length > 0}
        <h4 class="oc-label">{t('pack.allow.companies')}</h4>
        <div class="pm-rules">
          {#each choices.companies as company (company.uid)}
            <Checkbox label={company.name} hint={hintFor(company.uid, storedCompanies)} disabled={busy || locked(company.uid, storedCompanies)}
              bind:checked={() => companiesOn.includes(company.uid), (on) => (companiesOn = toggled(companiesOn, company.uid, on))}
              data-allow-company={company.uid} />
          {/each}
        </div>
      {/if}
      {#if unknownCompanies.length > 0}<p class="pm-note" data-allow="unknown-companies">{t('pack.allow.unknown_companies', { count: unknownCompanies.length })}</p>{/if}
      <h4 class="oc-label">{t('pack.allow.projects')}</h4>
      {#if choices.projects.length === 0}
        <p class="pm-note" data-allow="no-projects">{t('pack.allow.no_projects')}</p>
      {:else}
        <div class="pm-rules">
          {#each choices.projects as project (project.uid)}
            <Checkbox label={project.name} hint={hintFor(project.uid, storedProjects)} disabled={busy || locked(project.uid, storedProjects)}
              bind:checked={() => keptProjects.includes(project.uid), (on) => (projectsOn = toggled(projectsOn, project.uid, on))}
              data-allow-project={project.uid} />
          {/each}
        </div>
      {/if}
      {#if unknownProjects.length > 0}<p class="pm-note" data-allow="unknown-projects">{t('pack.allow.unknown_projects', { count: unknownProjects.length })}</p>{/if}
    {/if}
  {/if}
  {#if reason}<p class="pm-warn" data-allow="reason">{reason}</p>{/if}
  <div class="pm-actions">
    <Button variant="confirm" disabled={busy || !changed || reason !== '' || (mode === 'only' && !choices)} data-allow="save" onclick={save}>{t('pack.allow.save')}</Button>
  </div>
</div>
