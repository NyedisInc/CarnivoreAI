
<script lang="ts">
    import { onMount } from 'svelte';
    import { t as reactiveT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import { reasonOf } from '../launchpad/failure-reason';
    import Button from '../base/Button.svelte';
    import Field from '../base/Field.svelte';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import type { BrowseEntry, WizardApi } from './api';
    import { buildBreadcrumbs, joinChildPath, shortenPath } from './model';

    interface Props {
        initialDir: string;
        homeDir: string | null;
        recentFolders: readonly string[];
        api: WizardApi;
        t?: Translate;
        onSelect: (path: string) => void;
        onCancel: () => void;
    }

    let { initialDir, homeDir, recentFolders, api, t = reactiveT, onSelect, onCancel }: Props = $props();

    // svelte-ignore state_referenced_locally
    let currentDir = $state(initialDir);
    let entries = $state<BrowseEntry[]>([]);
    let loading = $state(false);
    let browseError = $state('');
    let newOpen = $state(false);
    let newName = $state('');
    let newError = $state('');
    let creating = $state(false);

    const crumbs = $derived(buildBreadcrumbs(currentDir, t('newagent.home_crumb'), homeDir));

    onMount(() => {
        void openDir(currentDir);
    });

    async function openDir(path: string): Promise<void> {
        loading = true;
        browseError = '';
        newOpen = false;
        newError = '';
        try {
            const res = await api.browseFolder(path);
            currentDir = res.path;
            entries = res.entries;
        } catch (err) {
            browseError = reasonOf(err, t);
        } finally {
            loading = false;
        }
    }

    async function handleCreateFolder(): Promise<void> {
        const clean = newName.trim().replace(/[\\/]/g, '');
        if (!clean) {
            newError = t('newagent.new_folder_required');
            return;
        }
        creating = true;
        newError = '';
        try {
            const target = joinChildPath(currentDir, clean);
            const res = await api.createFolder(target);
            currentDir = res.path;
            entries = res.entries;
            newOpen = false;
            newName = '';
        } catch (err) {
            newError = reasonOf(err, t);
        } finally {
            creating = false;
        }
    }

    function confirmCurrent(): void {
        api.rememberRecentFolder(currentDir);
        onSelect(currentDir);
    }
</script>

<div class="naw-step">
    <h2 class="naw-heading">{t('newagent.folder_heading')}</h2>

    <div class="naw-fp-toolbar">
        <nav class="naw-crumbs" aria-label={t('newagent.folder_heading')}>
            {#each crumbs as crumb, idx (crumb.path)}
                {#if idx > 0}
                    <span class="naw-crumb-sep" aria-hidden="true">/</span>
                {/if}
                <Button variant="quiet" size="sm" onclick={() => openDir(crumb.path)}>
                    <span class={idx === crumbs.length - 1 ? 'naw-crumb-current' : 'naw-crumb-label'}>
                        {crumb.label}
                    </span>
                </Button>
            {/each}
        </nav>
        <Button
            variant="secondary"
            size="sm"
            onclick={() => {
                newOpen = !newOpen;
                newName = '';
                newError = '';
            }}
        >
            <Icon name="plus" size={12} />
            <span>{t('newagent.new_folder_btn')}</span>
        </Button>
    </div>

    {#if newOpen}
        <div class="naw-new-folder-box">
            <div class="naw-new-folder-row">
                <div class="naw-grow">
                    <Field
                        aria-label={t('newagent.new_folder_label')}
                        placeholder={t('newagent.new_folder_placeholder')}
                        bind:value={newName}
                        error={newError || undefined}
                        block
                        onkeydown={(e) => {
                            if (e.key === 'Enter') {
                                e.preventDefault();
                                void handleCreateFolder();
                            }
                        }}
                    />
                </div>
                <Button variant="confirm" size="sm" disabled={creating} onclick={handleCreateFolder}>
                    {t('newagent.create_btn')}
                </Button>
                <Button
                    variant="secondary"
                    size="sm"
                    onclick={() => {
                        newOpen = false;
                        newError = '';
                    }}
                >
                    {t('newagent.cancel_btn')}
                </Button>
            </div>
        </div>
    {/if}

    {#if browseError}
        <div class="naw-error" role="alert">{browseError}</div>
    {/if}

    <div class="naw-fp-list" role="list" aria-label={t('newagent.folder_heading')}>
        {#if loading}
            <div class="naw-fp-empty">{t('newagent.loading')}</div>
        {:else if entries.length === 0}
            <div class="naw-fp-empty">{t('newagent.no_subfolders')}</div>
        {:else}
            {#each entries as entry (entry.path)}
                <div class="naw-fp-row" role="listitem">
                    <Button variant="row" size="auto" onclick={() => openDir(entry.path)}>
                        <span class="naw-fp-row-inner">
                            <span class="naw-fp-row-left">
                                <span class="naw-fp-icon"><Icon name="folder" size={14} /></span>
                                <span class="naw-ellipsis">{entry.name}</span>
                            </span>
                            <span class="naw-fp-chevron"><Icon name="chevron-right" size={12} /></span>
                        </span>
                    </Button>
                </div>
            {/each}
        {/if}
    </div>

    {#if recentFolders.length > 0}
        <div class="naw-field-group">
            <span class="naw-label">{t('newagent.recent_folders')}</span>
            <div class="naw-chip-row">
                {#each recentFolders as recent (recent)}
                    <Button variant="secondary" size="sm" onclick={() => openDir(recent)}>
                        {shortenPath(recent, homeDir)}
                    </Button>
                {/each}
            </div>
        </div>
    {/if}

    <div class="naw-current-bar">
        <span class="naw-label">{t('newagent.current_folder')}</span>
        <span class="naw-current-path" title={currentDir}>{currentDir}</span>
    </div>

    <div class="naw-footer-spread">
        <Button variant="secondary" onclick={onCancel}>{t('newagent.cancel_btn')}</Button>
        <Button variant="confirm" onclick={confirmCurrent}>{t('newagent.use_folder_btn')}</Button>
    </div>
</div>

<style>
    @layer components {
        .naw-step {
            display: flex;
            flex-direction: column;
            gap: var(--oc-space-4);
            padding: var(--oc-space-2) var(--oc-space-2) var(--oc-space-5);
        }

        .naw-heading {
            margin: 0;
            color: var(--oc-text-bright);
            font-size: var(--oc-fs-heading);
            line-height: var(--oc-lh-tight);
        }

        .naw-fp-toolbar {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: var(--oc-space-2);
            flex-wrap: wrap;
        }

        .naw-crumbs {
            display: flex;
            align-items: center;
            flex-wrap: wrap;
            gap: var(--oc-space-0-5);
            min-width: 0;
            flex: 1;
        }

        .naw-crumb-label {
            color: var(--oc-text-secondary);
            font-size: var(--oc-fs-label);
        }

        .naw-crumb-current {
            color: var(--oc-text-bright);
            font-size: var(--oc-fs-label);
        }

        .naw-crumb-sep {
            color: var(--oc-text-dim);
            font-size: var(--oc-fs-label);
            user-select: none;
        }

        .naw-new-folder-box {
            padding: var(--oc-space-2);
            border: var(--oc-border) solid var(--oc-line-frame);
            border-radius: var(--oc-radius-control);
            background: var(--oc-surface-1);
        }

        .naw-new-folder-row {
            display: flex;
            align-items: flex-start;
            gap: var(--oc-space-2);
        }

        .naw-grow {
            flex: 1;
            min-width: 0;
        }

        .naw-error {
            padding: var(--oc-space-2) var(--oc-space-3);
            border: var(--oc-border) solid var(--oc-coral);
            border-radius: var(--oc-radius-control);
            background: color-mix(in oklab, var(--oc-coral) 14%, transparent);
            color: var(--oc-coral);
            font-size: var(--oc-fs-label);
        }

        .naw-fp-list {
            display: flex;
            flex-direction: column;
            border: var(--oc-border) solid var(--oc-line-panel);
            border-radius: var(--oc-radius-control);
            background: var(--oc-ground-field);
            max-height: 220px;
            overflow-y: auto;
        }

        .naw-fp-row {
            display: flex;
            flex-direction: column;
            align-items: stretch;
            border-bottom: var(--oc-border) solid var(--oc-line-rule);
        }

        .naw-fp-row:last-child {
            border-bottom: 0;
        }

        .naw-fp-row-inner {
            width: 100%;
            min-height: 36px;
            padding: var(--oc-space-2) var(--oc-space-3);
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: var(--oc-space-2);
            min-width: 0;
        }

        .naw-fp-row-left {
            display: flex;
            align-items: center;
            gap: var(--oc-space-2);
            min-width: 0;
            flex: 1;
        }

        .naw-fp-icon {
            display: inline-flex;
            align-items: center;
            color: var(--oc-text-muted);
            flex-shrink: 0;
        }

        .naw-fp-chevron {
            display: inline-flex;
            align-items: center;
            color: var(--oc-text-muted);
            flex-shrink: 0;
        }

        .naw-ellipsis {
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            min-width: 0;
        }

        .naw-fp-empty {
            padding: var(--oc-space-4);
            color: var(--oc-text-muted);
            font-size: var(--oc-fs-label);
            text-align: center;
        }

        .naw-field-group {
            display: flex;
            flex-direction: column;
            gap: var(--oc-space-1-5);
        }

        .naw-label {
            color: var(--oc-text-muted);
            font-size: var(--oc-fs-micro);
            letter-spacing: var(--oc-tracking-caps);
            text-transform: uppercase;
        }

        .naw-chip-row {
            display: flex;
            flex-wrap: wrap;
            gap: var(--oc-space-1-5);
        }

        .naw-current-bar {
            padding: var(--oc-space-2) var(--oc-space-3);
            border: var(--oc-border) solid var(--oc-line-panel);
            border-radius: var(--oc-radius-control);
            background: var(--oc-surface-sunken);
            display: flex;
            flex-direction: column;
            gap: var(--oc-space-0-5);
            min-width: 0;
        }

        .naw-current-path {
            color: var(--oc-text-bright);
            font-size: var(--oc-fs-label);
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .naw-footer-spread {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: var(--oc-space-2);
            padding-top: var(--oc-space-2);
        }
    }
</style>
