
<script lang="ts">
    import { t as reactiveT } from '../i18n/index.svelte';
    import Button from '../base/Button.svelte';
    import List from '../base/List.svelte';
    import ListRow from '../base/ListRow.svelte';
    import Segmented from '../base/Segmented.svelte';
    import State from '../base/State.svelte';
    import Tag from '../base/Tag.svelte';
    import type { Translate } from '../sessions/types';
    import {
        bundleFilename,
        BundleFileError,
        errorText,
        fetchBundle,
        parseBundleText,
        sendImport,
        type Fetcher,
        type ImportAnswer,
        type ImportMode,
    } from './config-bundle/api';

    interface Props {
        t?: Translate;
        fetcher?: Fetcher;
        save?: (name: string, text: string) => void;
    }
    const { t = reactiveT, fetcher, save = downloadText }: Props = $props();

    function downloadText(name: string, text: string): void {
        const url = URL.createObjectURL(new Blob([text], { type: 'application/json' }));
        const link = document.createElement('a');
        link.href = url;
        link.download = name;
        link.click();
        URL.revokeObjectURL(url);
    }

    let busy = $state(false);
    let note = $state('');
    let problem = $state('');
    let mode = $state<ImportMode>('merge');
    let bundle = $state<Record<string, unknown> | null>(null);
    let preview = $state<ImportAnswer | null>(null);
    let picker: HTMLInputElement | undefined = $state();

    const total = $derived(preview ? preview.counts.added + preview.counts.changed + preview.counts.removed : 0);

    async function doExport(): Promise<void> {
        busy = true;
        problem = '';
        note = '';
        try {
            const file = await fetchBundle(fetcher);
            const name = bundleFilename(file);
            save(name, JSON.stringify(file, null, 2));
            note = t('settings.configbundle.exported', { file: name });
        } catch (error) {
            problem = errorText(error);
        } finally {
            busy = false;
        }
    }

    async function runPreview(): Promise<void> {
        if (!bundle) return;
        busy = true;
        problem = '';
        try {
            preview = await sendImport(bundle, mode, true, fetcher);
        } catch (error) {
            preview = null;
            problem = errorText(error);
        } finally {
            busy = false;
        }
    }

    async function onFile(event: Event): Promise<void> {
        const input = event.currentTarget as HTMLInputElement;
        const file = input.files?.[0];
        input.value = '';
        note = '';
        problem = '';
        preview = null;
        bundle = null;
        if (!file) return;
        try {
            bundle = parseBundleText(await file.text());
        } catch (error) {
            problem = error instanceof BundleFileError ? t('settings.configbundle.bad_file') : errorText(error);
            return;
        }
        await runPreview();
    }

    async function setMode(next: ImportMode): Promise<void> {
        if (mode === next) return;
        mode = next;
        if (bundle) await runPreview();
    }

    function cancel(): void {
        bundle = null;
        preview = null;
        problem = '';
    }

    async function apply(): Promise<void> {
        if (!bundle) return;
        busy = true;
        problem = '';
        try {
            const done = await sendImport(bundle, mode, false, fetcher);
            note =
                done.status === 'applied'
                    ? t('settings.configbundle.done', {
                          count: done.counts.added + done.counts.changed + done.counts.removed,
                      })
                    : t('settings.configbundle.done_none');
            bundle = null;
            preview = null;
        } catch (error) {
            problem = errorText(error);
        } finally {
            busy = false;
        }
    }
</script>

<div class="cb">
    <div class="cb__row">
        <Button data-cb="export" disabled={busy} onclick={() => void doExport()}>
            {t('settings.configbundle.export')}
        </Button>
        <Button data-cb="import" disabled={busy} onclick={() => picker?.click()}>
            {t('settings.configbundle.import')}
        </Button>
        <input
            bind:this={picker}
            class="cb__file"
            type="file"
            accept="application/json,.json"
            aria-label={t('settings.configbundle.import')}
            onchange={(e) => void onFile(e)}
        />
    </div>
    <p class="cb__hint">{t('settings.configbundle.no_secrets')}</p>

    {#if note}<State inline title={note} role="status" data-cb="note" />{/if}
    {#if problem}<State kind="error" inline title={problem} data-cb="problem" />{/if}

    {#if preview}
        <section class="cb__preview" data-cb="preview" aria-label={t('settings.configbundle.preview_title')}>
            <div class="pl-label">{t('settings.configbundle.preview_title')}</div>
            <Segmented
                label={t('settings.configbundle.mode_label')}
                bind:value={() => mode, (next) => void setMode(next as ImportMode)}
                disabled={busy}
                options={['merge', 'replace'].map((option) => ({ value: option, label: t(`settings.configbundle.mode.${option}`), attrs: { 'data-cb-mode': option } }))}
            />
            {#if preview.source.from_other_host}
                <State kind="warn" inline title={t('settings.configbundle.other_host', { host: preview.source.source_host })} />
            {/if}
            {#if preview.stripped.length}
                <p class="cb__hint">{t('settings.configbundle.stripped', { count: preview.stripped.length })}</p>
            {/if}
            {#if preview.ignored.length}
                <p class="cb__hint">{t('settings.configbundle.ignored', { names: preview.ignored.join(', ') })}</p>
            {/if}
            {#if total === 0}
                <p class="cb__hint" data-cb="empty">{t('settings.configbundle.no_changes')}</p>
            {:else}
                <p class="cb__hint">{t('settings.configbundle.change_count', { count: total })}</p>
                <List class="cb__changes" label={t('settings.configbundle.preview_title')}>
                    {#snippet children()}
                        {#each preview!.changes as line (line.path)}
                            <ListRow wrap class="cb__change" data-kind={line.kind} primary={line.path}>
                                {#snippet lead()}
                                    <Tag tone={line.kind === 'removed' ? 'danger' : 'neutral'}>{t(`settings.configbundle.kind.${line.kind}`)}</Tag>
                                {/snippet}
                                {#snippet secondary()}
                                    {#if line.before !== null}<s>{line.before}</s>{/if}
                                    {#if line.after !== null}<span>{line.after}</span>{/if}
                                {/snippet}
                            </ListRow>
                        {/each}
                    {/snippet}
                </List>
                {#if preview.truncated}
                    <p class="cb__hint">{t('settings.configbundle.truncated', { count: preview.changes.length })}</p>
                {/if}
            {/if}
            <div class="cb__actions">
                <Button data-cb="cancel" disabled={busy} onclick={cancel}>
                    {t('settings.configbundle.cancel')}
                </Button>
                <Button variant="confirm" data-cb="apply" disabled={busy} onclick={() => void apply()}>
                    {busy ? t('settings.configbundle.working') : t('settings.configbundle.apply')}
                </Button>
            </div>
        </section>
    {/if}
</div>

<style>
    .cb {
        display: flex;
        flex-direction: column;
        gap: var(--oc-space-4);
        width: 100%;
    }

    .cb__row,
    .cb__actions {
        display: flex;
        flex-wrap: wrap;
        gap: var(--oc-space-2);
    }

    .cb__actions {
        justify-content: flex-end;
    }

    .cb__file {
        display: none;
    }

    .cb__hint {
        margin: 0;
        font-family: var(--oc-font);
        font-size: var(--oc-fs-body);
        color: var(--oc-text-dim);
    }

    .cb__preview {
        display: flex;
        flex-direction: column;
        gap: var(--oc-space-3);
    }

    .cb__preview :global(.cb__changes) {
        max-height: 320px;
        overflow-y: auto;
    }
</style>
