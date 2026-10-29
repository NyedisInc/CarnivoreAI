
<script lang="ts">
    import { onDestroy, onMount, untrack } from 'svelte';
    import { t as reactiveT, type Translate } from '../sdk';
    import { Button, Checkbox, Field, IconButton, ModalShell, Tag } from '../sdk/ui';
    import { bytesText, errorCode, errorSentence, type Fetcher, type JobView } from './crate-api';
    import { unitLabel } from './store-label';
    import { changedImportPlan, hasConflicts, previewImport, provenanceSentence, skipSentence, startImport, type ImportPlanView, type ImportRequest, type ImportSource } from './import-api';
    import { parseImportReceipt } from './import-receipt';
    import ImportPreview from './ImportPreview.svelte';
    import ImportResult from './ImportResult.svelte';
    import JobProgress from './JobProgress.svelte';
    import TtyBox from './TtyBox.svelte';
    import './crate-dialog.css';

    interface Props {
        source: ImportSource;
        subject: string;
        originalRoot?: string | null;
        close: (value: string | null) => void;
        t?: Translate;
        fetcher?: Fetcher;
    }
    const { source, subject, originalRoot = null, close, t = reactiveT, fetcher }: Props = $props();

    const openedWith = untrack(() => originalRoot?.trim() || null);
    let restoreInto = $state(openedWith ?? '');
    let original = $state<string | null>(openedWith);
    let fieldTouched = false;
    const into = $derived(restoreInto.trim());
    const mode = $derived<'same_paths' | 'relocate'>(into !== '' && into !== original ? 'relocate' : 'same_paths');
    const newRoot = $derived(mode === 'relocate' ? into : null);
    let identity = $state('');
    let askKey = $state(false);
    let includeInstructions = $state(false);
    let includeProjectFiles = $state(true);
    let workInRestoredCopy = $state(true);
    let includePluginData = $state(true);
    let keepConversations = $state(true);
    let fileBackups = $state(true);
    let unticked = $state<readonly string[]>([]);
    let madeHere = $state(false);
    let skipConflicts = $state(false);
    let plan = $state<ImportPlanView | null>(null);
    let shown = $state<ImportPlanView | null>(null);
    let pending: ReturnType<typeof setTimeout> | null = null;
    const REPREVIEW_MS = 400;
    let busy = $state(false);
    let note = $state('');
    let problem = $state('');
    let jobId = $state<string | null>(null);
    let finished = $state<JobView | null>(null);
    let waiting = $state<'preview' | 'import' | null>(null);
    let elapsed = $state(0);
    let ticker: ReturnType<typeof setInterval> | null = null;

    const carries = $derived(shown?.carries ?? null);
    const showFiles = $derived(!!carries?.projectFiles);
    const showCopy = $derived(!!carries?.workInRestoredCopy);
    const showPlugins = $derived(!!carries?.pluginData);
    const backupFolders = $derived(shown?.backups?.folders ?? []);
    const showBackups = $derived(!!shown?.backups?.conversations.length && shown?.provenance === 'foreign');
    const folderLocked = (f: { status: string; reason: string | null }): boolean => backupsOff || (f.status === 'not_restored' && f.reason !== 'backups_not_chosen');
    const fileBackupUnits = $derived(shown?.provenance === 'foreign'
        ? backupFolders.filter((f) => !folderLocked(f) && !unticked.includes(f.unit)).map((f) => f.unit) : []);
    const backupsOff = $derived(shown?.backups?.providerEnabled === false);
    const showKeep = $derived(!!shown?.cleanup?.needsGuard);
    const request = $derived<ImportRequest>({
        source, mode, newRoot, skipConflicts, includeInstructions, madeHere, keepConversations, fileBackups, fileBackupUnits,
        identity: identity || null,
        includeProjectFiles,
        workInRestoredCopy: showFiles && showCopy && includeProjectFiles && workInRestoredCopy,
        includePluginData,
    });
    const filesHint = $derived.by(() => {
        const folder = shown?.projectFolder;
        if (folder?.files === 'into_project_folder') return t('cplug.crate.import.project_files_into', { folder: folder.path });
        if (folder?.files === 'beside_project_folder') return t('cplug.crate.import.project_files_beside', { folder: folder.side ?? '' });
        return t('cplug.crate.import.project_files_hint');
    });
    const canRestore = $derived(!!plan && plan.ok && plan.startAvailable && !!plan.fingerprint && !busy && jobId === null);
    const suggested = $derived(shown?.project?.suggestedRoot ?? null);
    const rootUnusable = $derived(!!shown?.blockers.some((b) => b.code === 'relocate_required'));
    const boxPlan = $derived(plan ? { ...plan, blockers: plan.blockers.filter((b) => b.code !== 'relocate_required') } : null);
    const receipt = $derived(finished?.state === 'done' ? parseImportReceipt(finished.result) : null);
    const foreign = $derived(shown?.provenance === 'foreign');
    const claimsHere = $derived(shown?.provenanceReason === 'claims_this_computer_not_proven');
    const landsIn = $derived(shown?.project?.rootTo ?? shown?.projectFolder?.path ?? (mode === 'relocate' ? into : null));
    const existingFolder = $derived.by(() => {
        const project = shown?.project;
        if (!project || (project.action !== 'attach' && project.action !== 'follow_uid') || !project.rootTo) return null;
        return project.rootTo !== (into || original) ? project.rootTo : null;
    });
    const totals = $derived(shown && shown.conversations.length
        ? t('cplug.crate.import.preview.counts', {
            conversations: shown.conversations.filter((c) => c.cls === 'write' || c.cls === 'grow').length,
            files: shown.files ?? 0, size: bytesText(shown.bytes) })
        : null);

    function invalidate(): void {
        plan = null;
        note = '';
    }

    function cancelPending(): void {
        if (pending !== null) clearTimeout(pending);
        pending = null;
    }

    function touch(delay = REPREVIEW_MS): void {
        invalidate();
        cancelPending();
        if (shown === null && askKey) return;
        pending = setTimeout(() => { pending = null; void previewNow(); }, delay);
    }

    async function previewNow(): Promise<void> {
        cancelPending();
        if (busy) {
            pending = setTimeout(() => { pending = null; void previewNow(); }, 150);
            return;
        }
        await preview();
    }

    function commit(): void {
        if (shown !== null && plan === null && !busy) void previewNow();
    }

    function startWaiting(kind: 'preview' | 'import'): void {
        stopWaiting();
        waiting = kind;
        elapsed = 0;
        const began = Date.now();
        ticker = setInterval(() => { elapsed = Math.floor((Date.now() - began) / 1000); }, 1000);
    }

    function stopWaiting(): void {
        if (ticker !== null) clearInterval(ticker);
        ticker = null;
        waiting = null;
    }

    onDestroy(() => { stopWaiting(); cancelPending(); });

    onMount(() => { void preview(0, true); });

    function useSuggested(): void {
        if (!suggested) return;
        fieldTouched = true;
        restoreInto = suggested;
        invalidate();
        void previewNow();
    }

    async function preview(depth = 0, atOpen = false): Promise<void> {
        const asked = `${request.includeProjectFiles}${request.workInRestoredCopy}${request.includePluginData}${request.fileBackupUnits}`;
        const askedInto = into;
        busy = true;
        problem = '';
        note = '';
        startWaiting('preview');
        let again = false;
        try {
            const answer = await previewImport(request, fetcher);
            plan = answer;
            shown = answer;
            if (into !== askedInto) plan = null;
            askKey = false;
            if (original === null && answer.project?.rootFrom) {
                original = answer.project.rootFrom;
                if (!fieldTouched && restoreInto === '') restoreInto = original;
            }
            again = `${request.includeProjectFiles}${request.workInRestoredCopy}${request.includePluginData}${request.fileBackupUnits}` !== asked;
        } catch (error) {
            plan = null;
            if (errorCode(error) === 'needs_identity') askKey = true;
            problem = atOpen && askKey ? '' : errorSentence(error, t);
        } finally {
            stopWaiting();
            busy = false;
        }
        if (again && depth < 2) await preview(depth + 1);
    }

    async function go(): Promise<void> {
        if (!plan?.fingerprint) return;
        busy = true;
        problem = '';
        startWaiting('import');
        try {
            jobId = await startImport(request, plan.fingerprint, fetcher);
            identity = '';
        } catch (error) {
            const fresh = errorCode(error) === 'plan_changed' ? changedImportPlan(error) : null;
            if (fresh) {
                plan = fresh;
                shown = fresh;
                note = t('cplug.crate.import.plan_changed');
            } else {
                problem = errorSentence(error, t);
            }
        } finally {
            stopWaiting();
            busy = false;
        }
    }

    function onFinish(job: JobView): void {
        finished = job;
    }
</script>

<ModalShell title={t('cplug.crate.import.title', { subject })} overlayClass={jobId === null ? 'text-prompt-modal crt-modal crt-modal--fill' : 'text-prompt-modal crt-modal'} dismissable={!busy} onCancel={() => close(null)}>
    {#snippet head()}
        <div class="text-prompt-modal__head">
            <span class="text-prompt-modal__verb">{t('cplug.crate.import.title', { subject })}</span>
            <IconButton label={t('modal.close')} icon="close" variant="close" iconSize={14} onclick={() => close(null)} />
        </div>
    {/snippet}
    {#if jobId === null}
        <dl class="crt-sum" data-crt-import-summary>
            <dt class="crt-sum__key">{t('cplug.crate.import.sum.crate')}</dt>
            <dd class="crt-sum__val crt-sum__val--bright" title={subject}>{subject}</dd>
            <dt class="crt-sum__key">{t('cplug.crate.import.sum.source')}</dt>
            {#if shown?.provenance}
                <dd class="crt-sum__val" title={provenanceSentence(shown.provenanceReason, t)}>{t(`cplug.crate.import.provenance_label.${shown.provenance}`)}</dd>
            {:else}
                <dd class="crt-sum__val crt-sum__val--unread">{t('cplug.crate.import.sum.unread')}</dd>
            {/if}
            <dt class="crt-sum__key">{t('cplug.crate.import.sum.lands')}</dt>
            <dd class={landsIn ? 'crt-sum__val' : 'crt-sum__val crt-sum__val--unread'} title={landsIn ?? undefined}>{landsIn ?? t('cplug.crate.import.sum.unread')}</dd>
            <dt class="crt-sum__key">{t('cplug.crate.import.sum.totals')}</dt>
            <dd class={totals ? 'crt-sum__val' : 'crt-sum__val crt-sum__val--unread'} data-crt-import-counts>{totals ?? t('cplug.crate.import.sum.unread')}</dd>
        </dl>
        <div class="crt-form" data-crt-form>
            <Field label={t('cplug.crate.import.restore_into')} help={t('cplug.crate.import.restore_into_hint')} maxlength={1024} bind:value={restoreInto} disabled={busy} autocomplete="off" spellcheck="false"
                oninput={() => { fieldTouched = true; touch(); }} onblur={commit} onkeydown={(e) => { if (e.key === 'Enter') commit(); }} data-crt-import-new-root />
            {#if existingFolder}
                <p class="tm__sub" role="status" data-crt-import-existing-folder>{t('cplug.crate.import.existing_folder', { folder: existingFolder })}</p>
            {/if}
            {#if rootUnusable}
                <p class="tm__problem" role="status" data-crt-root-unusable>{t('cplug.crate.import.root_unusable', { folder: original ?? '' })}</p>
                {#if suggested && into !== suggested}
                    <Button variant="secondary" data-crt-import-suggested disabled={busy} onclick={useSuggested}>
                        {t('cplug.crate.import.use_suggested', { folder: suggested })}
                    </Button>
                {/if}
            {/if}
            {#if askKey}
                <Field label={t('cplug.crate.import.key')} help={t('cplug.crate.import.key_hint')} type="password" bind:value={identity} disabled={busy} autocomplete="off" spellcheck="false"
                    oninput={invalidate} onblur={commit} onkeydown={(e) => { if (e.key === 'Enter') commit(); }} data-crt-import-key />
            {/if}
            <div class="crt-ticks">
                {#if showFiles}
                    <Checkbox bind:checked={() => includeProjectFiles, (next) => { includeProjectFiles = next; touch(); }} label={t('cplug.crate.import.project_files')} hint={filesHint} disabled={busy} data-crt-import-project-files="" />
                {/if}
                {#if showFiles && showCopy}
                    <Checkbox bind:checked={() => workInRestoredCopy, (next) => { workInRestoredCopy = next; touch(); }} label={t('cplug.crate.import.work_in_copy')} hint={t('cplug.crate.import.work_in_copy_hint')} disabled={busy || !includeProjectFiles} data-crt-import-work-in-copy="" />
                {/if}
                {#if showPlugins}
                    <Checkbox bind:checked={() => includePluginData, (next) => { includePluginData = next; touch(); }} label={t('cplug.crate.import.plugin_data')} hint={t('cplug.crate.import.plugin_data_hint')} disabled={busy} data-crt-import-plugin-data="" />
                {/if}
                {#if showBackups}
                    <Checkbox bind:checked={() => fileBackups && !backupsOff, (next) => { fileBackups = next; touch(); }} label={t('cplug.crate.import.file_backups')} hint={backupsOff ? t('cplug.crate.import.file_backups_off') : t('cplug.crate.import.file_backups_hint')} disabled={busy || backupsOff} data-crt-import-file-backups="" />
                {/if}
                {#if showBackups || (shown?.provenance === 'foreign' && backupFolders.length)}
                    {#each backupFolders.filter(() => shown?.provenance === 'foreign') as f (f.unit)}
                        <Checkbox bind:checked={() => !folderLocked(f) && !unticked.includes(f.unit), (next) => { unticked = next ? unticked.filter((u) => u !== f.unit) : [...unticked, f.unit]; touch(); }} label={t('cplug.crate.import.file_backups_family', { family: unitLabel(f.unit, t) })} hint={backupsOff ? t('cplug.crate.import.file_backups_off') : folderLocked(f) ? skipSentence(f.reason ?? '', t) : t('cplug.crate.import.file_backups_hint')} disabled={busy || folderLocked(f)} data-crt-import-backup-family={f.unit} />
                    {/each}
                {/if}
                {#if showKeep}
                    <Checkbox bind:checked={() => keepConversations, (next) => { keepConversations = next; touch(); }} label={t('cplug.crate.import.keep_conversations')} hint={t('cplug.crate.import.keep_conversations_hint', { period: shown?.cleanup?.periodDays ?? 30 })} disabled={busy} data-crt-import-keep-conversations="" />
                {/if}
                {#if foreign && (shown?.heldBack || includeInstructions)}
                    <Checkbox bind:checked={() => includeInstructions, (next) => { includeInstructions = next; touch(); }} label={t('cplug.crate.import.instructions')} hint={t('cplug.crate.import.instructions_hint')} disabled={busy} data-crt-import-instructions="" />
                {/if}
                {#if claimsHere || madeHere}
                    <Checkbox bind:checked={() => madeHere, (next) => { madeHere = next; touch(); }} label={t('cplug.crate.import.made_here')} hint={t('cplug.crate.import.made_here_hint')} disabled={busy} data-crt-import-made-here="" />
                {/if}
                {#if hasConflicts(shown) || skipConflicts}
                    <Checkbox bind:checked={() => skipConflicts, (next) => { skipConflicts = next; touch(); }} label={t('cplug.crate.import.skip_conflicts')} hint={t('cplug.crate.import.skip_conflicts_hint')} disabled={busy} data-crt-import-skip-conflicts="" />
                {/if}
            </div>
        </div>
        <TtyBox label={t('cplug.crate.box.label')}>
            {#snippet bar()}
                {#if waiting}
                    <span class="crt-measure" role="status" data-crt-measuring={waiting}>
                        <span class="crt-measure__dot" aria-hidden="true"></span>
                        <span class="crt-measure__sub">{t(waiting === 'import' ? 'cplug.crate.import.starting' : 'cplug.crate.import.measuring')}</span>
                        <span class="crt-measure__figs" data-crt-elapsed>{t('cplug.crate.import.elapsed', { seconds: elapsed })}</span>
                    </span>
                {:else if plan}
                    <Tag tone={plan.ok ? 'ok' : 'danger'}>{t(plan.ok ? 'cplug.crate.box.ready' : 'cplug.crate.box.blocked')}</Tag>
                {/if}
            {/snippet}
            {#if plan}
                <ImportPreview plan={boxPlan ?? plan} {t} />
            {:else}
                <p class="crt-tty__idle">{t(shown ? 'cplug.crate.import.box.stale' : 'cplug.crate.import.explain')}</p>
            {/if}
        </TtyBox>
        {#if plan?.ok && !plan.startAvailable}<p class="tm__note" role="status" data-crt-start-unavailable>{t('cplug.crate.import.start_unavailable')}</p>{/if}
        {#if note}<p class="tm__note" role="status" data-crt-note>{note}</p>{/if}
    {:else if receipt}
        <ImportResult {receipt} {t} {fetcher} />
    {:else}
        <JobProgress {jobId} {t} {fetcher} {onFinish} />
    {/if}
    {#if problem}<p class="tm__problem" role="alert" data-crt-problem>{problem}</p>{/if}
    {#snippet footer()}
        {#if jobId === null}
            <Button variant="secondary" disabled={busy} onclick={() => close(null)}>{t('cplug.crate.import.cancel')}</Button>
            {#if plan?.ok || shown?.ok}
                <Button variant="confirm" data-crt-go disabled={!canRestore} onclick={() => void go()}>{t('cplug.crate.import.go')}</Button>
            {:else}
                <Button variant="confirm" data-crt-preview disabled={busy} onclick={() => void preview()}>{t(waiting === 'preview' ? 'cplug.crate.import.previewing' : 'cplug.crate.import.preview')}</Button>
            {/if}
        {:else}
            <Button variant="secondary" data-crt-close onclick={() => close(finished?.state === 'done' ? jobId : null)}>
                {finished ? t('cplug.crate.import.done') : t('cplug.crate.import.hide')}
            </Button>
        {/if}
    {/snippet}
</ModalShell>
