<script lang="ts">
    import { untrack } from 'svelte';
    import '../ledger/ledger-chrome.css';
    import Button from '../base/Button.svelte';
    import GitDiffView from '../../opscenter/cells/terminal-live/GitDiffView.svelte';
    import { t } from '../i18n/index.svelte';
    import { readOpenFile, type CantShowReason, type OpenFileContent, type OpenFileInfo } from './api.svelte';
    import { bufferOf, dropBuffer, isDirty, loadBuffer, reveal, setCurrent } from './buffers.svelte';
    import EditorControls from '../editor-controls/EditorControls.svelte';
    import FileEditor from './FileEditor.svelte';
    import { fileSaveLight } from './file-save-light';
    import { closeFileRow } from './open-bridge';
    import { appConfirm, saveFile } from './save-flow';
    import { sessionIdForUuid } from './session-ref';

    let { file }: { file: OpenFileInfo } = $props();

    type Phase = 'loading' | 'ready' | 'cant' | 'diff' | 'error';

    let phase = $state<Phase>('loading');
    let cant = $state<{ reason: CantShowReason; detail: string } | null>(null);
    let errorText = $state('');
    let stale = $state(false);
    let staleGone = $state(false);
    let saving = $state(false);
    let failed = $state(false);
    let message = $state<{ tone: 'ok' | 'error'; text: string } | null>(null);
    let mode = $state<'edit' | 'preview'>('edit');
    let revision = $state(0);
    let diffSessionId = $state<string | null>(null);

    const id = $derived(file.id);
    const buffer = $derived(bufferOf(id));
    const dirty = $derived(isDirty(id));
    const readOnly = $derived(buffer?.readOnly ?? false);
    const masked = $derived(!!buffer && buffer.isSensitive && !buffer.revealed);
    const isMarkdown = $derived(/\.(md|markdown)$/i.test(file.path));
    const writable = $derived(file.kind === 'file' && phase === 'ready' && !readOnly && !masked);
    const showMode = $derived(phase === 'ready' && isMarkdown && !masked);
    const light = $derived(fileSaveLight({ writable, dirty, saving, stale, failed }));
    const showSave = $derived(file.kind === 'file' && phase === 'ready' && !readOnly);
    const saveDisabled = $derived(!writable || !dirty || saving);

    async function load(rowId: string, force: boolean): Promise<void> {
        if (!force && bufferOf(rowId)) {
            phase = 'ready';
            return;
        }
        phase = 'loading';
        try {
            const read = await readOpenFile(rowId);
            if (rowId !== id) return;
            show(rowId, read);
        } catch (err) {
            if (rowId !== id) return;
            console.warn('open files: the file could not be read', { id: rowId, error: err });
            errorText = err instanceof Error ? err.message : String(err);
            phase = 'error';
        }
    }

    function show(rowId: string, read: OpenFileContent): void {
        if (!read.viewable) {
            dropBuffer(rowId);
            cant = { reason: read.reason ?? 'unavailable', detail: read.detail ?? '' };
            phase = 'cant';
            return;
        }
        loadBuffer(rowId, read);
        revision += 1;
        phase = 'ready';
    }

    async function loadDiff(row: OpenFileInfo): Promise<void> {
        phase = 'loading';
        try {
            const sessionId = await sessionIdForUuid(row.session_uuid);
            if (row.id !== id) return;
            if (!sessionId) {
                cant = { reason: 'unavailable', detail: '' };
                phase = 'cant';
                return;
            }
            diffSessionId = sessionId;
            phase = 'diff';
        } catch (err) {
            if (row.id !== id) return;
            console.warn('open files: the diff session could not be found', { id: row.id, error: err });
            errorText = err instanceof Error ? err.message : String(err);
            phase = 'error';
        }
    }

    const rowKey = $derived(`${file.id}:${file.kind}`);

    $effect(() => {
        void rowKey;
        untrack(() => {
            stale = false;
            staleGone = false;
            failed = false;
            message = null;
            cant = null;
            mode = /\.(md|markdown)$/i.test(file.path) ? 'preview' : 'edit';
            if (file.kind === 'diff') void loadDiff(file);
            else void load(file.id, false);
        });
    });

    async function save(overwrite = false): Promise<void> {
        if (saving || readOnly || phase !== 'ready' || masked) return;
        saving = true;
        failed = false;
        message = null;
        const outcome = await saveFile(id, file.path, overwrite);
        saving = false;
        if (outcome.kind === 'saved') {
            stale = false;
            staleGone = false;
            message = { tone: 'ok', text: t(outcome.backedUp ? 'files.editor.saved_backup' : 'files.editor.saved') };
        } else if (outcome.kind === 'stale') {
            stale = true;
            staleGone = outcome.gone;
        } else if (outcome.kind === 'invalid_json') {
            failed = true;
            message = { tone: 'error', text: t('files.editor.invalid_json', { detail: outcome.detail }) };
        } else if (outcome.kind === 'failed') {
            failed = true;
            message = { tone: 'error', text: t('files.editor.save_failed', { detail: outcome.detail }) };
        }
    }

    async function reloadFromDisk(): Promise<void> {
        message = null;
        const rowId = id;
        let read: OpenFileContent;
        try {
            read = await readOpenFile(rowId);
        } catch (err) {
            if (rowId !== id) return;
            console.warn('open files: the reload could not read the file', { id: rowId, error: err });
            message = { tone: 'error', text: t('files.screen.read_failed', { detail: err instanceof Error ? err.message : String(err) }) };
            return;
        }
        if (rowId !== id) return;
        if (!read.viewable && read.reason === 'gone') {
            stale = true;
            staleGone = true;
            return;
        }
        stale = false;
        staleGone = false;
        failed = false;
        show(rowId, read);
    }

    async function revealContents(): Promise<void> {
        const ok = await appConfirm()(t('files.editor.reveal.title'), t('files.editor.reveal.message', { path: file.path }),
            t('files.editor.reveal.detail'), t('files.editor.reveal.confirm'), t('files.editor.reveal.cancel'));
        if (ok) reveal(id);
    }

    function onKeydown(event: KeyboardEvent): void {
        if ((event.metaKey || event.ctrlKey) && !event.altKey && event.key.toLowerCase() === 's') {
            event.preventDefault();
            if (dirty) void save(false);
        }
    }

    function pressDisk(): void {
        if (stale) {
            document.querySelector<HTMLButtonElement>(`[data-file-id="${id}"] [data-file-stale] button`)?.focus();
            return;
        }
        void save(false);
    }

    function preview(text: string): string {
        const md = (globalThis as { MarkdownLite?: { render?: (s: string) => string } }).MarkdownLite;
        return typeof md?.render === 'function' ? md.render(text) : '';
    }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="fscreen pledger" data-file-screen={file.kind} data-file-id={file.id} onkeydown={onKeydown}>
    <div class="pl-titlebar">
        <span class="pl-title">{t(file.kind === 'diff' ? 'files.screen.diff' : 'files.screen.file')}</span>
        <bdi class="fs-path" title={file.path}>{file.path}</bdi>
        {#if dirty}<span class="fs-flag" data-file-dirty="">{t('files.editor.unsaved')}</span>{/if}
        {#if file.kind === 'diff' || readOnly}<span class="fs-flag fs-flag--quiet">{t('files.editor.read_only')}</span>{/if}
        <span class="fs-actions">
            
            <EditorControls {mode} onMode={(next) => { mode = next; }} showMode={showMode} showSave={showSave}
                light={light} saveState={saving ? 'saving' : ''} saveDisabled={saveDisabled} onSave={pressDisk}
                onClose={() => void closeFileRow(id)} closeLabelKey="files.editor.close"
                saveProps={{ 'data-file-save': '' }} closeProps={{ 'data-file-close': '' }} />
        </span>
    </div>
    {#if stale}
        <div class="fs-stale" role="alert" data-file-stale="">
            <span class="fs-stale-text">{t(staleGone ? 'files.editor.stale.deleted' : 'files.editor.stale')}</span>
            <Button onclick={() => { stale = false; }}>{t('files.editor.stale.keep')}</Button>
            {#if !staleGone}
                <Button data-file-reload="" onclick={() => void reloadFromDisk()}>{t('files.editor.stale.reload')}</Button>
            {/if}
            <Button variant="danger" data-file-overwrite="" onclick={() => void save(true)}>{t('files.editor.stale.overwrite')}</Button>
        </div>
    {/if}
    {#if message}
        <p class="fs-msg" data-tone={message.tone} role="status">{message.text}</p>
    {/if}
    <div class="fs-body">
        {#if phase === 'loading'}
            <p class="fs-note" role="status">{t('files.screen.loading')}</p>
        {:else if phase === 'error'}
            <p class="fs-note" role="alert">{t('files.screen.read_failed', { detail: errorText })}</p>
        {:else if phase === 'cant' && cant}
            <div class="fs-cant" data-file-cant={cant.reason}>
                <p class="fs-cant-title">{t(`files.cant.${cant.reason}`)}</p>
                {#if cant.detail}<p class="fs-cant-detail">{cant.detail}</p>{/if}
            </div>
        {:else if phase === 'diff' && diffSessionId}
            <div class="fs-diff" data-file-diff="">
                <GitDiffView sessionId={diffSessionId} path={file.path} />
            </div>
        {:else if phase === 'ready' && buffer}
            {#if masked}
                <div class="fs-mask" data-file-masked="">
                    <p class="fs-cant-title">{t('files.editor.masked')}</p>
                    <Button onclick={() => void revealContents()}>{t('files.editor.reveal')}</Button>
                </div>
            {:else}
                {#key revision}
                    <div class="fs-edit" hidden={mode === 'preview'}>
                        <FileEditor text={buffer.current} path={file.path} {readOnly}
                            onChange={(value) => setCurrent(id, value)}
                            onUnavailable={(detail) => { errorText = detail; phase = 'error'; }} />
                    </div>
                {/key}
                {#if mode === 'preview'}
                    
                    <div class="fs-preview"><article class="fs-doc">{@html preview(buffer.current)}</article></div>
                {/if}
            {/if}
        {/if}
    </div>
</div>

<style>
    @layer components {
        .fscreen {
            display: flex;
            flex-direction: column;
            width: 100%;
            height: 100%;
            min-height: 0;
            background: var(--oc-ground-page);
            color: var(--oc-text-primary);
            font-family: var(--font-mono);
        }

        .fscreen :global(.pl-titlebar) {
            border-radius: 0;
            flex: 0 0 auto;
        }

        .fs-path {
            min-width: 0;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            font-size: 12px;
            color: var(--oc-text-secondary);
        }

        .fs-flag {
            font-size: var(--oc-fs-micro, 10px);
            letter-spacing: var(--oc-tracking-label, 0.6px);
            text-transform: uppercase;
            color: var(--oc-yellow);
            white-space: nowrap;
        }

        .fs-flag--quiet {
            color: var(--oc-text-muted);
        }

        .fs-actions {
            margin-left: auto;
            display: flex;
            align-items: center;
            gap: var(--oc-space-2);
            flex: 0 0 auto;
        }

        .fs-stale {
            display: flex;
            align-items: center;
            flex-wrap: wrap;
            gap: var(--oc-space-2);
            padding: var(--oc-space-2) var(--oc-space-3);
            background: var(--oc-ground-panel);
            box-shadow: inset 0 -1px 0 0 var(--oc-line-rule);
            flex: 0 0 auto;
        }

        .fs-stale-text {
            flex: 1 1 240px;
            font-size: 12px;
            color: var(--oc-yellow);
        }

        .fs-msg {
            margin: 0;
            padding: var(--oc-space-1-5) var(--oc-space-3);
            font-size: 12px;
            color: var(--oc-text-secondary);
            box-shadow: inset 0 -1px 0 0 var(--oc-line-faint);
            flex: 0 0 auto;
        }

        .fs-msg[data-tone='error'] {
            color: var(--oc-coral);
        }

        .fs-body {
            flex: 1 1 auto;
            min-height: 0;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }

        .fs-edit {
            flex: 1 1 auto;
            min-height: 0;
            display: flex;
            flex-direction: column;
            padding: var(--oc-space-2);
        }

        .fs-edit[hidden] {
            display: none;
        }

        .fs-diff {
            flex: 1 1 auto;
            min-height: 0;
            overflow: auto;
            padding: var(--oc-space-3);
        }

        .fs-preview {
            flex: 1 1 auto;
            min-height: 0;
            overflow: auto;
            padding: var(--oc-gutter);
        }

        .fs-doc {
            width: 100%;
            min-width: 0;
            font-size: 14px;
            line-height: 1.7;
            color: var(--oc-text-primary);
            overflow-wrap: anywhere;
        }

        .fs-doc :global(> :first-child) {
            margin-top: 0;
        }

        .fs-doc :global(p),
        .fs-doc :global(ul),
        .fs-doc :global(ol),
        .fs-doc :global(blockquote),
        .fs-doc :global(pre),
        .fs-doc :global(table) {
            margin: 0 0 1.1em;
        }

        .fs-doc :global(h1),
        .fs-doc :global(h2),
        .fs-doc :global(h3),
        .fs-doc :global(h4),
        .fs-doc :global(h5),
        .fs-doc :global(h6) {
            color: var(--oc-text-bright);
            font-weight: 600;
            line-height: 1.3;
            margin: 1.8em 0 0.6em;
        }

        .fs-doc :global(h1) {
            font-size: 24px;
            padding-bottom: 0.4em;
            box-shadow: inset 0 -1px 0 0 var(--oc-line-rule);
        }

        .fs-doc :global(h2) {
            font-size: 19px;
            padding-bottom: 0.3em;
            box-shadow: inset 0 -1px 0 0 var(--oc-line-faint);
        }

        .fs-doc :global(h3) {
            font-size: 16px;
        }

        .fs-doc :global(h4) {
            font-size: 14px;
            letter-spacing: var(--oc-tracking-label, 0.6px);
            text-transform: uppercase;
            color: var(--oc-text-secondary);
        }

        .fs-doc :global(h5),
        .fs-doc :global(h6) {
            font-size: 13px;
            color: var(--oc-text-secondary);
        }

        .fs-doc :global(ul),
        .fs-doc :global(ol) {
            padding-left: 1.6em;
        }

        .fs-doc :global(li) {
            margin: 0 0 0.35em;
        }

        .fs-doc :global(strong) {
            color: var(--oc-text-bright);
        }

        .fs-doc :global(a) {
            color: var(--oc-orange);
            text-decoration: underline;
            text-underline-offset: 2px;
        }

        .fs-doc :global(a:hover) {
            color: var(--oc-orange-bright);
        }

        .fs-doc :global(blockquote) {
            padding: var(--oc-space-0-5) 0 var(--oc-space-0-5) calc(var(--oc-space-3) + var(--oc-space-0-5));
            box-shadow: inset 2px 0 0 0 var(--oc-line-rule);
            color: var(--oc-text-secondary);
        }

        .fs-doc :global(code) {
            font-family: var(--font-mono);
            font-size: 0.9em;
            padding: calc(var(--oc-space-0-5) / 2) calc(var(--oc-space-1) + var(--oc-space-0-5) / 2);
            background: var(--oc-ground-raised);
            border-radius: var(--oc-radius-sm);
        }

        .fs-doc :global(pre) {
            max-width: 100%;
            padding: var(--oc-space-3) calc(var(--oc-space-3) + var(--oc-space-0-5));
            overflow-x: auto;
            font-size: 13px;
            line-height: 1.55;
            background: var(--oc-ground-raised);
            border: 1px solid var(--oc-line-rule);
            border-radius: var(--oc-radius-sm);
        }

        .fs-doc :global(pre code) {
            padding: 0;
            background: none;
            font-size: inherit;
            overflow-wrap: normal;
            white-space: pre;
        }

        .fs-doc :global(hr) {
            border: 0;
            height: 1px;
            margin: 1.8em 0;
            background: var(--oc-line-rule);
        }

        .fs-doc :global(table) {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }

        .fs-doc :global(th),
        .fs-doc :global(td) {
            padding: var(--oc-space-1-5) calc(var(--oc-space-2) + var(--oc-space-0-5));
            text-align: left;
            vertical-align: top;
            border: 1px solid var(--oc-line-rule);
        }

        .fs-doc :global(th) {
            background: var(--oc-ground-titlerow);
            color: var(--oc-text-secondary);
            font-size: var(--oc-fs-micro, 10px);
            letter-spacing: var(--oc-tracking-label, 0.6px);
            text-transform: uppercase;
        }

        .fs-note {
            margin: 0;
            padding: var(--oc-space-3);
            color: var(--oc-text-dim);
            font-size: 13px;
        }

        .fs-cant,
        .fs-mask {
            display: flex;
            flex-direction: column;
            align-items: flex-start;
            gap: var(--oc-space-2);
            padding: var(--oc-space-4) var(--oc-space-3);
        }

        .fs-cant-title {
            margin: 0;
            font-size: 13px;
            color: var(--oc-text-primary);
        }

        .fs-cant-detail {
            margin: 0;
            font-size: 12px;
            color: var(--oc-text-muted);
        }
    }
</style>
