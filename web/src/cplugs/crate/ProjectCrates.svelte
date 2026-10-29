<script lang="ts">
  import { openModal, resourcePush, t } from '../sdk';
  import type { PanelReadState, ProjectPanelProps } from '../sdk';
  import { errorSentence, fetchBundles, isRemoved, presentCopies, verifyBundle, type BundleView } from './crate-api';
  import { downloadCrate } from './undo-api';
  import ExportDialog from './ExportDialog.svelte';
  import ImportDialog from './ImportDialog.svelte';
  import JobProgress from './JobProgress.svelte';
  import RemoveDialog from './RemoveDialog.svelte';

  const POLL_MS = 30000;
  const EXPORTS_TOPIC = 'exports';

  const { projectId, header, isFolded, age, previewOf }: ProjectPanelProps = $props();

  let crates = $state<BundleView[]>([]);
  let loaded = $state(false);
  let failed = $state(false);
  let expanded = $state(false);
  let jobId = $state<string | null>(null);
  let running = $state(false);
  let problem = $state('');
  let downloading = $state<string | null>(null);
  let generation = 0;

  const count = $derived(crates.length);
  const read: PanelReadState = $derived(!loaded ? 'loading' : failed && count === 0 ? 'failed' : 'ready');
  const folded = $derived(isFolded(false));
  const shown = $derived(previewOf(count, expanded));

  async function load(id: number): Promise<void> {
    const mine = ++generation;
    try {
      const answer = await fetchBundles(id);
      if (mine !== generation) return;
      crates = answer;
      failed = false;
    } catch (err) {
      if (mine !== generation) return;
      console.warn('crate: project crates read failed', { project: id, error: err instanceof Error ? err.message : String(err) });
      failed = true;
    } finally {
      if (mine === generation) loaded = true;
    }
  }

  function copiesText(crate: BundleView): string {
    return isRemoved(crate) ? t('cplug.crate.panel.removed') : allThere(crate) ? t('cplug.crate.project.copies_ok', { count: crate.locations.length }) : t('cplug.crate.project.copies_missing');
  }

  async function exportProject(): Promise<void> {
    const done = await openModal<string, Record<string, unknown>>(ExportDialog as never, {
      scope: 'project', target: String(projectId), subject: t('cplug.crate.project.subject'),
    });
    if (done) void load(projectId);
  }

  async function restore(crate: BundleView): Promise<void> {
    const done = await openModal<string, Record<string, unknown>>(ImportDialog as never, {
      source: { bundleId: crate.bundleId }, subject: crate.label ?? crate.bundleId, originalRoot: crate.projectRoot,
    });
    if (done) void load(projectId);
  }

  async function remove(crate: BundleView): Promise<void> {
    const done = await openModal<boolean, Record<string, unknown>>(RemoveDialog as never, {
      target: { bundleId: crate.bundleId }, name: crate.label ?? crate.bundleId, recorded: true, otherCopy: presentCopies(crate) > 1,
    });
    if (done) void load(projectId);
  }

  async function verify(crate: BundleView): Promise<void> {
    problem = '';
    try {
      jobId = await verifyBundle(crate.bundleId, 'full');
      running = true;
    } catch (err) {
      problem = errorSentence(err, t);
    }
  }

  async function download(crate: BundleView): Promise<void> {
    downloading = crate.bundleId;
    problem = '';
    try {
      await downloadCrate({ bundleId: crate.bundleId }, crate.label ?? crate.bundleId);
    } catch (err) {
      problem = errorSentence(err, t);
    } finally {
      downloading = null;
    }
  }

  function allThere(crate: BundleView): boolean {
    return crate.locations.length > 0 && crate.locations.every((l) => l.state === 'present');
  }

  $effect(() => {
    const id = projectId;
    crates = [];
    loaded = false;
    failed = false;
    expanded = false;
    jobId = null;
    void load(id);
    return resourcePush().pushOrPoll(() => void load(id), POLL_MS, [EXPORTS_TOPIC]);
  });
</script>

{@render header(count, read)}
{#if !folded}
  <div class="crt-pacts">
    <button type="button" class="oc-btn oc-btn--sm oc-btn--confirm" data-crt-export-project onclick={() => void exportProject()}>
      {t('cplug.crate.project.export')}
    </button>
  </div>
  {#if read === 'failed'}
    <p class="ph-empty" data-crt-failed><span class="ph-gone">{t('cplug.crate.project.failed')}</span></p>
  {:else if read === 'ready' && count === 0}
    <p class="ph-empty">{t('cplug.crate.project.empty')}</p>
  {:else}
    {#each crates.slice(0, shown) as crate (crate.bundleId)}
      {@const name = crate.label ?? crate.bundleId}
      <div class="crt-prow ph-scols" data-crt-crate={crate.bundleId}>
        <span class="crt-prow__lead"></span>
        <span class="crt-prow__name">{name}</span>
        <span class="crt-prow__meta">
          <span><span class="ph-tag">{t(`cplug.crate.panel.scope.${crate.scope === 'project' ? 'project' : 'session'}`)}</span></span>
          <span><span class="ph-tag" data-crt-copies={isRemoved(crate) ? 'removed' : allThere(crate) ? 'present' : 'missing'} title={copiesText(crate)}>
            {copiesText(crate)}
          </span></span>
        </span>
        <span class="crt-prow__when">{age(crate.createdAt)}</span>
        <span class="crt-prow__act">
          {#if !isRemoved(crate)}
          <button type="button" class="oc-btn oc-btn--sm" data-crt-restore={crate.bundleId} disabled={running}
            aria-label={t('cplug.crate.project.restore_label', { name })} onclick={() => void restore(crate)}>{t('cplug.crate.import.restore')}</button>
          <button type="button" class="oc-btn oc-btn--sm" data-crt-verify={crate.bundleId} disabled={running}
            aria-label={t('cplug.crate.project.verify_label', { name })} onclick={() => void verify(crate)}>{t('cplug.crate.panel.verify')}</button>
          {#if presentCopies(crate) > 0}
          <button type="button" class="oc-btn oc-btn--sm" data-crt-download={crate.bundleId} disabled={downloading !== null}
            aria-label={t('cplug.crate.project.download_label', { name })} onclick={() => void download(crate)}>{t(downloading === crate.bundleId ? 'cplug.crate.panel.downloading' : 'cplug.crate.panel.download')}</button>
          <button type="button" class="oc-btn oc-btn--sm" data-crt-remove={crate.bundleId} disabled={running}
            aria-label={t('cplug.crate.project.remove_label', { name })} onclick={() => void remove(crate)}>{t('cplug.crate.panel.remove')}</button>
          {/if}
          {/if}
        </span>
        <span class="crt-prow__pad"></span>
      </div>
    {/each}
    {#if shown < count}
      <button type="button" class="oc-btn crt-pmore" data-show-all onclick={() => (expanded = true)}>
        {t('projects.page.show_all', { count })}
      </button>
    {/if}
    {#if failed}<p class="ph-empty" data-crt-failed><span class="ph-gone">{t('cplug.crate.project.failed')}</span></p>{/if}
  {/if}
  {#if jobId}
    <div class="crt-pjob"><JobProgress {jobId} onFinish={() => { running = false; void load(projectId); }} /></div>
  {/if}
  {#if problem}<p class="ph-empty"><span class="ph-gone" role="alert">{problem}</span></p>{/if}
{/if}

<style>
  @layer components {
    .crt-pacts,
    .crt-pjob {
      display: flex;
      padding: var(--oc-space-2) var(--oc-space-3);
    }

    .crt-pjob {
      flex-direction: column;
    }

    .crt-prow {
      grid-template-columns: 16px minmax(0, 1fr) 72px 160px 56px 288px 24px;
      min-height: 28px;
      box-shadow: inset 0 -1px 0 var(--oc-line-faint);
    }

    .crt-prow:hover {
      background: var(--oc-ground-hover);
    }

    .crt-prow__meta {
      display: contents;
    }

    .crt-prow__meta > span {
      display: flex;
      min-width: 0;
    }

    .crt-prow__meta > span > span {
      flex: 0 1 auto;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .crt-prow__name {
      display: flex;
      align-items: center;
      min-width: 0;
      overflow: hidden;
      font-weight: 500;
      color: var(--oc-text-primary);
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .crt-prow__when {
      font-size: var(--oc-fs-label, 11px);
      font-variant-numeric: tabular-nums;
      color: var(--oc-text-secondary);
      text-align: right;
      white-space: nowrap;
    }

    .crt-prow__act {
      display: flex;
      gap: var(--oc-space-2);
      justify-self: end;
    }

    .crt-pmore {
      margin: var(--oc-space-1) var(--oc-space-3);
    }

    @container ph (max-width: 767px) {
      .crt-prow {
        grid-template-columns: 16px minmax(0, 1fr) auto auto auto;
        grid-template-areas:
          'lead name when act kebab'
          'lead meta meta act kebab';
        column-gap: var(--oc-space-2);
        row-gap: 0;
        min-height: 48px;
        padding-block: 2px;
      }

      .crt-prow__lead { grid-area: lead; }
      .crt-prow__name { grid-area: name; }
      .crt-prow__when { grid-area: when; }
      .crt-prow__act { grid-area: act; grid-row: 1 / 3; align-self: center; }
      .crt-prow__pad { grid-area: kebab; grid-row: 1 / 3; width: 44px; min-width: 44px; }

      .crt-prow__meta {
        display: flex;
        grid-area: meta;
        align-items: center;
        gap: var(--oc-space-2);
        min-width: 0;
        font-size: var(--oc-fs-label, 11px);
        color: var(--oc-text-dim);
      }
    }
  }
</style>
