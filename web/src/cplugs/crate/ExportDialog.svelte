
<script lang="ts">
    import { onDestroy } from 'svelte';
    import { t as reactiveT, type Translate } from '../sdk';
    import { Button, Checkbox, Field, IconButton, ModalShell, Radio, RadioGroup, Tag } from '../sdk/ui';
    import {
        bytesText,
        changedPlan,
        codeSentence,
        errorSentence,
        fetchBackupFamilies,
        fetchSummary,
        previewPlan,
        startExport,
        type BackupFamily,
        type ExportRequest,
        type Fetcher,
        type JobView,
        type PlanView,
        unencryptedFindings,
    } from './crate-api';
    import JobProgress from './JobProgress.svelte';
    import { unitLabel } from './store-label';
    import TtyBox from './TtyBox.svelte';
    import './crate-dialog.css';

    interface Props {
        scope: 'session' | 'project';
        target: string;
        subject: string;
        close: (value: string | null) => void;
        t?: Translate;
        fetcher?: Fetcher;
    }
    const { scope, target, subject, close, t = reactiveT, fetcher }: Props = $props();

    const VARIANTS = ['own', 'share'] as const;
    const LABEL_MAX = 80;

    let variant = $state<'own' | 'share'>('own');
    let encrypt = $state(false);
    let label = $state('');
    let projectFiles = $state(false);
    let includeBackups = $state(false);
    let backupsAvailable = $state<boolean | null>(null);
    let families = $state<readonly BackupFamily[]>([]);
    let ticked = $state<readonly string[]>([]);
    let recipients = $state(0);
    let plan = $state<PlanView | null>(null);
    let busy = $state(false);
    let note = $state('');
    let problem = $state('');
    let jobId = $state<string | null>(null);
    let finished = $state<JobView | null>(null);
    let waiting = $state<'preview' | 'export' | null>(null);
    let elapsed = $state(0);
    let ticker: ReturnType<typeof setInterval> | null = null;

    const request = $derived<ExportRequest>({ scope, target, variant, encrypt: variant === 'share' ? false : encrypt, label: label.trim() || null,
        includeProjectFiles: variant === 'own' && projectFiles, includeBackups: variant === 'own' && includeBackups && backupsAvailable !== false,
        backupUnits: variant === 'own' ? families.filter((f) => f.state === 'ok' && ticked.includes(f.unit)).map((f) => f.unit) : [] });
    const findings = $derived(unencryptedFindings(finished));
    const canExport = $derived(!!plan && plan.ok && !!plan.fingerprint && !busy && jobId === null);

    async function loadDefaults(): Promise<void> {
        try {
            const summary = await fetchSummary(fetcher);
            encrypt = summary.encryptDefault === true && summary.recipients.length > 0;
            recipients = summary.recipients.length;
            backupsAvailable = summary.backupsAvailable;
        } catch (error) {
            problem = errorSentence(error, t);
        }
    }
    void loadDefaults();

    async function loadFamilies(): Promise<void> {
        try {
            families = (await fetchBackupFamilies(scope, target, fetcher)).folders;
        } catch {
            families = [];
        }
    }
    void loadFamilies();

    function pluginName(family: BackupFamily): string {
        const named = family.pluginNameKey ? t(family.pluginNameKey) : '';
        return named && named !== family.pluginNameKey ? named : family.plugin;
    }

    function familyName(family: BackupFamily): string {
        return unitLabel(family.unit, t, family.pluginNameKey);
    }

    function tick(unit: string, next: boolean): void {
        ticked = next ? [...ticked.filter((u) => u !== unit), unit] : ticked.filter((u) => u !== unit);
        invalidate();
    }

    function invalidate(): void {
        plan = null;
        note = '';
    }

    function startWaiting(kind: 'preview' | 'export'): void {
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

    onDestroy(stopWaiting);

    async function preview(): Promise<void> {
        busy = true;
        problem = '';
        note = '';
        startWaiting('preview');
        try {
            plan = await previewPlan(request, fetcher);
        } catch (error) {
            plan = null;
            problem = errorSentence(error, t);
        } finally {
            stopWaiting();
            busy = false;
        }
    }

    async function go(): Promise<void> {
        if (!plan?.fingerprint) return;
        busy = true;
        problem = '';
        startWaiting('export');
        try {
            jobId = await startExport(request, plan.fingerprint, fetcher);
        } catch (error) {
            const fresh = changedPlan(error);
            if (fresh) {
                plan = fresh;
                note = t('cplug.crate.export.plan_changed');
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

<ModalShell title={t('cplug.crate.export.title', { subject })} overlayClass="text-prompt-modal crt-modal" dismissable={!busy} onCancel={() => close(null)}>
    {#snippet head()}
        <div class="text-prompt-modal__head">
            <span class="text-prompt-modal__verb">{t('cplug.crate.export.title', { subject })}</span>
            <IconButton label={t('modal.close')} icon="close" variant="close" iconSize={14} onclick={() => close(null)} />
        </div>
    {/snippet}
    {#if jobId === null}
        <p class="modal-description">{t(`cplug.crate.export.explain.${scope}`)}</p>
        <div class="crt-form" data-crt-form>
            <RadioGroup label={t('cplug.crate.export.copy')} disabled={busy} bind:value={() => variant, (next) => { variant = next as typeof variant; invalidate(); }}>
                {#each VARIANTS as value (value)}
                    <Radio {value} label={t(`cplug.crate.export.${value}`)} hint={t(`cplug.crate.export.${value}_hint`)} data-crt-variant={value} />
                {/each}
            </RadioGroup>
            {#if variant === 'own'}
                <Checkbox bind:checked={() => encrypt, (next) => { encrypt = next; invalidate(); }} label={t('cplug.crate.export.encrypt')} hint={recipients > 0 ? t('cplug.crate.export.encrypt_hint', { count: recipients }) : t('cplug.crate.export.encrypt_none')} disabled={busy || recipients === 0} data-crt-encrypt="" />
                <Checkbox bind:checked={() => projectFiles, (next) => { projectFiles = next; invalidate(); }} label={t('cplug.crate.export.project_files')} hint={t('cplug.crate.export.project_files_hint')} disabled={busy} data-crt-project-files="" />
                <Checkbox bind:checked={() => includeBackups && backupsAvailable !== false, (next) => { includeBackups = next; invalidate(); }} label={t('cplug.crate.export.include_backups')} hint={backupsAvailable === false ? t('cplug.crate.export.include_backups_off') : t('cplug.crate.export.include_backups_hint')} disabled={busy || backupsAvailable === false} data-crt-include-backups="" />
                {#each families as family (family.unit)}
                    <Checkbox bind:checked={() => family.state === 'ok' && ticked.includes(family.unit), (next) => { tick(family.unit, next); }} label={t('cplug.crate.export.include_folder_backups', { name: familyName(family) })} hint={family.state === 'ok' ? t('cplug.crate.export.include_folder_backups_hint', { name: familyName(family) }) : t(`cplug.crate.export.backup_folder_${family.state}`, { name: familyName(family), plugin: pluginName(family) })} disabled={busy || family.state !== 'ok'} data-crt-backup-folder={family.unit} />
                {/each}
            {:else}
                <p class="tm__sub" data-crt-share-note>{t('cplug.crate.export.share_note')}</p>
            {/if}
            <Field label={t('cplug.crate.export.label')} maxlength={LABEL_MAX} bind:value={label} disabled={busy} autocomplete="off"
                oninput={invalidate} data-crt-label />
        </div>
        {#if waiting || plan}
            <TtyBox label={t('cplug.crate.box.label')} fit>
                {#snippet bar()}
                    {#if waiting}
                        
                        <span class="crt-measure" role="status" data-crt-measuring={waiting}>
                            <span class="crt-measure__dot" aria-hidden="true"></span>
                            <span class="crt-measure__sub">{t(waiting === 'export' ? 'cplug.crate.export.starting' : projectFiles && variant === 'own' ? 'cplug.crate.export.measuring_files' : 'cplug.crate.export.measuring')}</span>
                            <span class="crt-measure__figs" data-crt-elapsed>{t('cplug.crate.export.elapsed', { seconds: elapsed })}</span>
                        </span>
                    {:else if plan}
                        <Tag tone={plan.ok ? 'ok' : 'danger'}>{t(plan.ok ? 'cplug.crate.box.ready' : 'cplug.crate.box.blocked')}</Tag>
                    {/if}
                {/snippet}
                {#if plan}
                    <div class="crt-tty__out crt-tty__out--lines" data-crt-plan={plan.ok ? 'ok' : 'blocked'}>
                        <p class="tm__figs" data-crt-plan-counts>
                            {t('cplug.crate.export.counts', { conversations: plan.conversations ?? 0, files: plan.files ?? 0, size: bytesText(plan.estimateBytes) })}
                        </p>
                        {#each plan.backupFamilies as carried (carried.unit)}
                            {@const family = families.find((f) => f.unit === carried.unit)}
                            <p class="tm__figs" data-crt-backup-family={carried.unit}>
                                {t('cplug.crate.export.backup_folder_counts', { name: family ? familyName(family) : carried.unit, points: carried.points ?? 0, files: carried.files ?? 0, size: bytesText(carried.bytes) })}
                            </p>
                        {/each}
                        {#if plan.folder}<p class="tm__sub" data-crt-plan-folder>{t('cplug.crate.export.into', { folder: plan.folder })}</p>{/if}
                        {#if plan.projectFiles}
                            {@const pf = plan.projectFiles}
                            <p class="tm__figs" data-crt-project-counts>{t('cplug.crate.export.project_counts', { files: pf.files ?? 0, size: bytesText(pf.bytes) })}</p>
                            {#if pf.skipped.length}
                                <p class="tm__sub" data-crt-project-skipped>{t('cplug.crate.export.project_skipped', { count: pf.skippedFolders ?? pf.skipped.length, size: bytesText(pf.skippedBytes) })}</p>
                                {#each pf.skipped as folder (folder.path)}
                                    <p class="tm__sub" data-crt-project-skipped-folder>{t('cplug.crate.export.project_skipped_one', { path: folder.path, size: bytesText(folder.bytes) })}</p>
                                {/each}
                                {#if (pf.skippedFolders ?? 0) > pf.skipped.length}
                                    <p class="tm__sub" data-crt-project-skipped-more>{t('cplug.crate.export.project_skipped_more', { count: (pf.skippedFolders ?? 0) - pf.skipped.length })}</p>
                                {/if}
                            {/if}
                            {#if pf.specials.length}<p class="tm__sub" data-crt-project-specials>{t('cplug.crate.export.project_specials', { names: pf.specials.join(', ') })}</p>{/if}
                            {#if pf.large}<p class="tm__warn" data-crt-project-large>{t('cplug.crate.export.project_large', { size: bytesText(pf.warnBytes) })}</p>{/if}
                        {/if}
                        {#if plan.excludedCount}<p class="tm__sub">{t('cplug.crate.export.excluded', { count: plan.excludedCount })}</p>{/if}
                        {#each plan.blockers as blocker, index (index)}
                            {@const said = codeSentence(blocker.code, blocker.detail, t)}
                            <p class="tm__problem" data-crt-blocker={blocker.code}>{said}</p>
                            {#if blocker.detail && blocker.detail !== said}<p class="tm__sub">{blocker.detail}</p>{/if}
                        {/each}
                        {#each plan.warnings as warning, index (index)}
                            <p class="tm__sub" data-crt-warning>{warning}</p>
                        {/each}
                    </div>
                {/if}
            </TtyBox>
        {/if}
        {#if note}<p class="tm__note" role="status" data-crt-note>{note}</p>{/if}
    {:else}
        <JobProgress {jobId} {t} {fetcher} {onFinish} />
        {#if findings > 0}<p class="tm__warn" role="status" data-crt-secrets-warning>{t('cplug.crate.export.secrets_warning', { count: findings })}</p>{/if}
    {/if}
    {#if problem}<p class="tm__problem" role="alert" data-crt-problem>{problem}</p>{/if}
    {#snippet footer()}
        {#if jobId === null}
            <Button variant="secondary" disabled={busy} onclick={() => close(null)}>{t('cplug.crate.export.cancel')}</Button>
            {#if plan?.ok}
                <Button variant="confirm" data-crt-go disabled={!canExport} onclick={() => void go()}>{t('cplug.crate.export.go')}</Button>
            {:else}
                <Button variant="confirm" data-crt-preview disabled={busy} onclick={() => void preview()}>{t(waiting === 'preview' ? 'cplug.crate.export.previewing' : 'cplug.crate.export.preview')}</Button>
            {/if}
        {:else}
            <Button variant="secondary" data-crt-close onclick={() => close(finished?.state === 'done' ? jobId : null)}>
                {finished ? t('cplug.crate.export.done') : t('cplug.crate.export.hide')}
            </Button>
        {/if}
    {/snippet}
</ModalShell>
