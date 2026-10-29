<!-- could not -->
<script lang="ts">
    import { familyOf, openModal, resourcePush, stampLabel, t as reactiveT, truncatedTip, type Translate } from '../sdk';
    import {
        JOBS_FAMILY,
        bytesText,
        copyBundle,
        errorSentence,
        fetchBundles,
        fetchSummary,
        isRemoved,
        presentCopies,
        verifyBundle,
        codeSentence,
        type BundleView,
        type Fetcher,
        type FolderView,
        type Summary,
    } from './crate-api';
    import { fetchFolderCrates, sendPicked, unrecorded, type FolderCrate, type RemoveTarget } from './folder-crates-api';
    import ImportDialog from './ImportDialog.svelte';
    import RemoveDialog from './RemoveDialog.svelte';
    import JobProgress from './JobProgress.svelte';
    import RestoredList from './RestoredList.svelte';
    import { downloadCrate, fetchRestored, type RestoredImport } from './undo-api';

    interface Props {
        t?: Translate;
        fetcher?: Fetcher;
    }
    const { t = reactiveT, fetcher }: Props = $props();

    const PREVIEW = 6;
    const EXPORTS_TOPIC = 'exports';
    const POLL_MS = 30000;

    let summary = $state<Summary | null>(null);
    let bundles = $state<BundleView[] | null>(null);
    let jobId = $state<string | null>(null);
    let running = $state(false);
    let expanded = $state(false);
    let busy = $state(false);
    let problem = $state('');
    let downloading = $state<string | null>(null);
    let found = $state<FolderCrate[] | null>(null);
    let foundProblem = $state('');
    let restored = $state<RestoredImport[] | null>(null);
    /*  hidden  */
    let sending = $state<string | null>(null);
    let picker = $state<HTMLInputElement | null>(null);

    const second = $derived(summary?.second ?? null);
    const shown = $derived(bundles ? (expanded ? bundles : bundles.slice(0, PREVIEW)) : []);
    const folderRows = $derived<[string, FolderView | null][]>(summary ? [['primary', summary.primary], ['second', second]] : []);

    async function load(): Promise<void> {
        try {
            const [s, b] = await Promise.all([fetchSummary(fetcher), fetchBundles(null, fetcher)]);
            summary = s;
            bundles = b;
            if (s.runningJob && !running) {
                jobId = s.runningJob.jobId;
                running = true;
            }
            problem = '';
        } catch (error) {
            problem = errorSentence(error, t);
        }
        await Promise.all([loadFound(), loadRestored()]);
    }

    async function loadRestored(): Promise<void> {
        try {
            restored = await fetchRestored(fetcher);
        } catch (error) {
            console.warn('crate: restored list read failed', { error: error instanceof Error ? error.message : String(error) });
        }
    }

    async function loadFound(): Promise<void> {
        const which = (['primary', 'second'] as const).filter((name) => (name === 'primary' ? true : second?.state === 'ok'));
        try {
            const lists = await Promise.all(which.map((name) => fetchFolderCrates(name, fetcher)));
            found = unrecorded(lists.flat());
            foundProblem = '';
        } catch (error) {
            foundProblem = errorSentence(error, t);
        }
    }

    async function download(key: string, target: RemoveTarget, name: string): Promise<void> {
        downloading = key;
        problem = '';
        try {
            await downloadCrate(target, name);
        } catch (error) {
            problem = errorSentence(error, t);
        } finally {
            downloading = null;
        }
    }

    async function run(start: () => Promise<string>): Promise<void> {
        busy = true;
        problem = '';
        try {
            jobId = await start();
            running = true;
        } catch (error) {
            problem = errorSentence(error, t);
        } finally {
            busy = false;
        }
    }

    function onFinish(): void {
        running = false;
        void load();
    }

    function folderLine(folder: FolderView): string {
        if (folder.state === 'ok') return t('cplug.crate.panel.folder_ok', { free: bytesText(folder.freeBytes) });
        return t(`cplug.crate.panel.folder_${folder.state === 'unmounted' ? 'unmounted' : 'unavailable'}`);
    }

    function inSecond(bundle: BundleView): boolean {
        const root = second?.path;
        return !!root && bundle.locations.some((l) => l.where.startsWith(root.endsWith('/') ? root : `${root}/`));
    }

    function locationWord(state: string | null): string {
        return t(`cplug.crate.panel.location.${state === 'present' || state === 'unmounted' ? state : 'missing'}`);
    }

    async function restore(bundle: BundleView): Promise<void> {
        const done = await openModal<string, Record<string, unknown>>(ImportDialog as never, {
            source: { bundleId: bundle.bundleId }, subject: bundle.label ?? bundle.bundleId, originalRoot: bundle.projectRoot, t, fetcher,
        });
        if (done) void load();
    }

    async function restoreFound(crate: FolderCrate): Promise<void> {
        const done = await openModal<string, Record<string, unknown>>(ImportDialog as never, {
            source: { folder: crate.folder, name: crate.name }, subject: crate.name, originalRoot: crate.projectRoot, t, fetcher,
        });
        if (done) void load();
    }

    async function removeRecorded(bundle: BundleView): Promise<void> {
        const done = await openModal<boolean, Record<string, unknown>>(RemoveDialog as never, {
            target: { bundleId: bundle.bundleId }, name: bundle.label ?? bundle.bundleId, recorded: true,
            otherCopy: presentCopies(bundle) > 1, t, fetcher,
        });
        if (done) void load();
    }

    async function removeFound(crate: FolderCrate): Promise<void> {
        const done = await openModal<boolean, Record<string, unknown>>(RemoveDialog as never, {
            target: { folder: crate.folder, name: crate.name }, name: crate.name, t, fetcher,
        });
        if (done) void load();
    }

    async function onPicked(): Promise<void> {
        const files = Array.from(picker?.files ?? []);
        if (picker) picker.value = '';
        if (files.length === 0) return;
        problem = '';
        try {
            sending = files.find((f) => !f.name.endsWith('.sha256'))?.name ?? files[0]!.name;
            const sent = await sendPicked(files, fetcher);
            if ('refused' in sent) {
                problem = codeSentence(sent.refused, null, t);
                return;
            }
            sending = null;
            await load();
            await restoreFound({ folder: 'primary', name: sent.name, size: sent.size, writtenAt: null, share: false, encrypted: sent.name.endsWith('.age'), bundleId: null, projectRoot: sent.projectRoot });
        } catch (error) {
            problem = errorSentence(error, t);
        } finally {
            sending = null;
        }
    }

    void load();

    $effect(() => {
        const push = resourcePush();
        const stopPoll = push.pushOrPoll(() => void load(), POLL_MS, [EXPORTS_TOPIC]);
        const stopFrames = push.onChange((topics) => {
            if (topics.some((topic) => familyOf(topic) === JOBS_FAMILY && topic !== `${JOBS_FAMILY}:${jobId}`)) void load();
        });
        return () => {
            stopPoll();
            stopFrames();
        };
    });
</script>

<div class="tm" data-crt-panel>
    <section class="crt-region" data-crt-folders>
        <span class="pl-label">{t('cplug.crate.panel.folders')}</span>
        {#if summary}
            {#each folderRows as [which, folder] (which)}
                {#if folder}
                    <div class="crt-row" data-crt-folder={which} data-crt-folder-state={folder.state}>
                        <span class="crt-row__name">{t(`cplug.crate.panel.folder.${which}`)}</span>
                        <span class="crt-row__meta">{folder.path ?? t('cplug.crate.panel.folder_default')}</span>
                        <span class={folder.state === 'ok' ? 'tm__sub' : 'tm__problem'}>{folderLine(folder)}</span>
                    </div>
                    {#if folder.state !== 'ok' && folder.reason}<p class="tm__sub">{folder.reason}</p>{/if}
                {/if}
            {/each}
            {#if !second}<p class="tm__sub" data-crt-no-second>{t('cplug.crate.panel.no_second')}</p>{/if}
        {:else if !problem}
            <p class="tm__sub">{t('cplug.crate.panel.reading')}</p>
        {/if}
    </section>

    {#if jobId}
        <section class="crt-region">
            <JobProgress {jobId} {t} {fetcher} {onFinish} />
        </section>
    {/if}

    <section class="crt-region" data-crt-bundles>
        <span class="pl-label">
            {summary?.bundles === null ? t('cplug.crate.panel.crates_unknown') : t('cplug.crate.panel.crates', { count: bundles?.length ?? 0 })}
        </span>
        {#if bundles && bundles.length === 0}
            <p class="tm__sub" data-crt-empty>{t('cplug.crate.panel.empty')}</p>
        {/if}
        {#each shown as bundle (bundle.bundleId)}
            <div class="crt-row" data-crt-bundle={bundle.bundleId}>
                <span class="crt-row__name">{bundle.label ?? bundle.bundleId}</span>
                <span class="crt-row__meta">
                    {t(`cplug.crate.panel.scope.${bundle.scope === 'project' ? 'project' : 'session'}`)}
                    {t('cplug.crate.panel.written', { when: stampLabel(bundle.createdAt) })}
                    {bundle.verifiedAt ? t('cplug.crate.panel.verified', { when: stampLabel(bundle.verifiedAt) }) : t('cplug.crate.panel.never_verified')}
                </span>
                {#if isRemoved(bundle)}
                    <span class="crt-row__where" data-crt-removed={bundle.bundleId}><span class="tm__sub">{t('cplug.crate.panel.removed')}</span></span>
                {:else}
                    <span class="crt-row__acts">
                        <button type="button" class="oc-btn oc-btn--sm" data-crt-restore={bundle.bundleId} disabled={busy || running}
                            onclick={() => void restore(bundle)}>{t('cplug.crate.import.restore')}</button>
                        <button type="button" class="oc-btn oc-btn--sm" data-crt-verify={bundle.bundleId} disabled={busy || running}
                            onclick={() => void run(() => verifyBundle(bundle.bundleId, 'full', fetcher))}>{t('cplug.crate.panel.verify')}</button>
                        {#if second?.state === 'ok' && !inSecond(bundle)}
                            <button type="button" class="oc-btn oc-btn--sm" data-crt-copy={bundle.bundleId} disabled={busy || running}
                                onclick={() => void run(() => copyBundle(bundle.bundleId, fetcher))}>{t('cplug.crate.panel.copy')}</button>
                        {/if}
                        {#if presentCopies(bundle) > 0}
                            <button type="button" class="oc-btn oc-btn--sm" data-crt-download={bundle.bundleId} disabled={downloading !== null}
                                aria-label={t('cplug.crate.panel.download_label', { name: bundle.label ?? bundle.bundleId })}
                                onclick={() => void download(bundle.bundleId, { bundleId: bundle.bundleId }, bundle.label ?? bundle.bundleId)}>{t(downloading === bundle.bundleId ? 'cplug.crate.panel.downloading' : 'cplug.crate.panel.download')}</button>
                            <button type="button" class="oc-btn oc-btn--sm" data-crt-remove={bundle.bundleId} disabled={busy || running}
                                onclick={() => void removeRecorded(bundle)}>{t('cplug.crate.panel.remove')}</button>
                        {/if}
                    </span>
                    {#each bundle.locations as location (location.where)}
                        <span class="crt-row__where" data-crt-location={location.state ?? 'missing'}>
                            <span class={location.state === 'present' ? 'tm__sub' : 'tm__problem'}>{locationWord(location.state)}</span>
                            {location.where}
                        </span>
                    {/each}
                {/if}
            </div>
        {/each}
        {#if bundles && bundles.length > shown.length}
            <button type="button" class="oc-btn oc-btn--sm" data-crt-show-all onclick={() => (expanded = true)}>
                {t('cplug.crate.panel.show_all', { count: bundles.length })}
            </button>
        {/if}
    </section>
    <RestoredList {restored} busy={busy || running} onChange={() => void load()} {t} {fetcher} />
    <section class="crt-region" data-crt-found>
        <span class="pl-label">{t('cplug.crate.found.label')}</span>
        <p class="tm__sub" data-crt-found-hint>{t('cplug.crate.found.hint')}</p>
        {#if found && found.length === 0 && !foundProblem}
            <p class="tm__sub" data-crt-found-empty>{t('cplug.crate.found.empty')}</p>
        {/if}
        {#each found ?? [] as crate (`${crate.folder}/${crate.share ? 'share/' : ''}${crate.name}`)}
            <div class="crt-row crt-row--line" data-crt-found-row={crate.name}>
                <span class="crt-row__name" use:truncatedTip={crate.name}>{crate.name}</span>
                <span class="crt-row__meta">
                    {bytesText(crate.size)}
                    {#if crate.writtenAt}{stampLabel(crate.writtenAt)}{/if}
                    {t(crate.share ? 'cplug.crate.found.share' : 'cplug.crate.found.own')}
                    {#if crate.encrypted}{t('cplug.crate.found.encrypted')}{/if}
                    {#if crate.folder === 'second'}{t('cplug.crate.found.second')}{/if}
                </span>
                <span class="crt-row__acts">
                    <button type="button" class="oc-btn oc-btn--sm" data-crt-restore-found={crate.name} disabled={busy || running || sending !== null}
                        onclick={() => void restoreFound(crate)}>{t('cplug.crate.import.restore')}</button>
                    <button type="button" class="oc-btn oc-btn--sm" data-crt-download-found={crate.name} disabled={downloading !== null}
                        aria-label={t('cplug.crate.panel.download_label', { name: crate.name })}
                        onclick={() => void download(`${crate.folder}/${crate.name}`, { folder: crate.folder, name: crate.name }, crate.name)}>{t(downloading === `${crate.folder}/${crate.name}` ? 'cplug.crate.panel.downloading' : 'cplug.crate.panel.download')}</button>
                    {#if !crate.share}
                        <button type="button" class="oc-btn oc-btn--sm" data-crt-remove-found={crate.name} disabled={busy || running || sending !== null}
                            onclick={() => void removeFound(crate)}>{t('cplug.crate.panel.remove')}</button>
                    {/if}
                </span>
            </div>
        {/each}
        {#if foundProblem}<p class="tm__problem" data-crt-found-problem>{t('cplug.crate.found.unreadable')} {foundProblem}</p>{/if}
        <span class="crt-row__acts">
            <input type="file" multiple accept=".crate,.age,.sha256" hidden bind:this={picker} data-crt-picker onchange={() => void onPicked()} />
            <button type="button" class="oc-btn oc-btn--sm" data-crt-open title={t('cplug.crate.found.open_hint')} disabled={busy || running || sending !== null}
                onclick={() => picker?.click()}>{t('cplug.crate.found.open')}</button>
            {#if sending}<span class="tm__sub" data-crt-sending>{t('cplug.crate.found.sending', { name: sending })}</span>{/if}
        </span>
    </section>
    {#if problem}<p class="tm__problem" role="alert" data-crt-problem>{problem}</p>{/if}
</div>

<style>
    @layer components {
        .crt-region {
            display: flex;
            flex-direction: column;
            gap: var(--oc-space-2);
            padding-top: var(--oc-space-3);
            box-shadow: inset 0 1px 0 var(--oc-line-faint);
        }

        .crt-region p {
            margin: 0;
        }

        .crt-row {
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            column-gap: var(--oc-space-3);
            row-gap: var(--oc-space-1);
            padding-block: var(--oc-space-2);
            box-shadow: inset 0 -1px 0 var(--oc-line-faint);
            font-size: var(--oc-fs-body);
        }

        .crt-row__name {
            overflow: hidden;
            color: var(--oc-text-bright);
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .crt-row__meta,
        .crt-row__where {
            grid-column: 1;
            overflow: hidden;
            font-size: var(--oc-fs-label, 11px);
            color: var(--oc-text-dim);
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .crt-row--line {
            grid-template-columns: minmax(0, 1fr) auto auto;
            align-items: center;
            padding-block: var(--oc-space-1);
        }

        .crt-row--line .crt-row__meta,
        .crt-row--line .crt-row__acts {
            grid-column: auto;
            grid-row: auto;
        }

        .crt-row--line .crt-row__meta {
            max-width: 14rem;
        }

        .crt-row__acts {
            display: flex;
            grid-column: 2;
            grid-row: 1 / 3;
            align-items: center;
            gap: var(--oc-space-2);
        }
    }
</style>
