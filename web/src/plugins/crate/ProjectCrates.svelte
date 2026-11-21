<script lang="ts">
  import { openModal, resourcePush, t } from '../sdk';
  import type { PanelReadState, ProjectPanelProps } from '../sdk';
  import { errorSentence, fetchBundles, isRemoved, presentCopies, verifyBundle, type BundleView } from './crate-api';
  import { downloadCrate } from './undo-api';
  import { Button, List, ListRow, Tag } from '../sdk/ui';
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
    running = false;
    problem = '';
    void load(id);
    return resourcePush().pushOrPoll(() => void load(id), POLL_MS, [EXPORTS_TOPIC]);
  });
</script>

{@render header(count, read)}
{#if !folded}
  <div class="crt-pacts">
    <Button size="sm" variant="confirm" data-crt-export-project onclick={() => void exportProject()}>
      {t('cplug.crate.project.export')}
    </Button>
  </div>
  {#if read === 'failed'}
    <p class="ph-empty" data-crt-failed><span class="ph-gone">{t('cplug.crate.project.failed')}</span></p>
  {:else if read === 'ready' && count === 0}
    <p class="ph-empty">{t('cplug.crate.project.empty')}</p>
  {:else}
    <List label={t('cplug.crate.project.group')}>
      {#snippet children()}
        {#each crates.slice(0, shown) as crate (crate.bundleId)}
          {@const name = crate.label ?? crate.bundleId}
          {#snippet below()}
            <span class="crt-pacts__line">
              <Tag>{t(`cplug.crate.panel.scope.${crate.scope === 'project' ? 'project' : 'session'}`)}</Tag>
              <Tag tone={isRemoved(crate) ? 'neutral' : allThere(crate) ? 'ok' : 'warn'} data-crt-copies={isRemoved(crate) ? 'removed' : allThere(crate) ? 'present' : 'missing'} title={copiesText(crate)}>
                {copiesText(crate)}
              </Tag>
            </span>
            {#if !isRemoved(crate)}
              <span class="crt-pacts__line">
                <Button size="sm" data-crt-restore={crate.bundleId} disabled={running}
                  aria-label={t('cplug.crate.project.restore_label', { name })} onclick={() => void restore(crate)}>{t('cplug.crate.import.restore')}</Button>
                <Button size="sm" data-crt-verify={crate.bundleId} disabled={running}
                  aria-label={t('cplug.crate.project.verify_label', { name })} onclick={() => void verify(crate)}>{t('cplug.crate.panel.verify')}</Button>
                {#if presentCopies(crate) > 0}
                  <Button size="sm" data-crt-download={crate.bundleId} disabled={downloading !== null}
                    aria-label={t('cplug.crate.project.download_label', { name })} onclick={() => void download(crate)}>{t(downloading === crate.bundleId ? 'cplug.crate.panel.downloading' : 'cplug.crate.panel.download')}</Button>
                  <Button size="sm" variant="danger" data-crt-remove={crate.bundleId} disabled={running}
                    aria-label={t('cplug.crate.project.remove_label', { name })} onclick={() => void remove(crate)}>{t('cplug.crate.panel.remove')}</Button>
                {/if}
              </span>
            {/if}
          {/snippet}
          <ListRow wrap data-crt-crate={crate.bundleId} primary={name} meta={age(crate.createdAt)} {below} />
        {/each}
      {/snippet}
    </List>
    {#if shown < count}
      <span class="crt-pacts">
        <Button size="sm" data-show-all onclick={() => (expanded = true)}>
          {t('projects.page.show_all', { count })}
        </Button>
      </span>
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

    .crt-pacts__line {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: var(--oc-space-2);
      padding-block: var(--oc-space-0-5);
    }
  }
</style>
