
<script lang="ts">
    import { t as reactiveT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import Button from '../base/Button.svelte';
    import Field from '../base/Field.svelte';
    import { extractRepoName, joinChildPath, shortenPath } from './model';

    interface Props {
        repoUrl: string;
        repoUrlError: string;
        projectName: string;
        parentDir: string;
        description: string;
        defaultDir: string;
        homeDir: string | null;
        onBrowse: () => void;
        onContinue: () => void;
        t?: Translate;
    }

    let {
        repoUrl = $bindable(''),
        repoUrlError,
        projectName = $bindable(''),
        parentDir,
        description = $bindable(''),
        defaultDir,
        homeDir,
        onBrowse,
        onContinue,
        t = reactiveT,
    }: Props = $props();

    const inferredName = $derived(extractRepoName(repoUrl));
    const effectiveParent = $derived(parentDir || defaultDir);
    const previewPath = $derived(
        inferredName ? joinChildPath(effectiveParent, inferredName) : effectiveParent,
    );

    function onKeyDown(e: KeyboardEvent): void {
        if (e.key === 'Enter') {
            e.preventDefault();
            onContinue();
        }
    }
</script>

<div class="naw-step">
    <h2 class="naw-heading">{t('newagent.clone_heading')}</h2>

    <Field
        label={t('newagent.clone_url_label')}
        placeholder={t('newagent.clone_url_placeholder')}
        bind:value={repoUrl}
        error={repoUrlError || undefined}
        autocomplete="off"
        block
        onkeydown={onKeyDown}
    />

    <Field
        label={t('newagent.clone_name_label')}
        placeholder={inferredName || t('newagent.project_name_placeholder')}
        bind:value={projectName}
        autocomplete="off"
        block
        onkeydown={onKeyDown}
    />

    <div class="naw-path-group">
        <span class="naw-section-label">{t('newagent.clone_parent_label')}</span>
        <div class="naw-path-box">
            <span class="naw-path-value" title={effectiveParent}>
                {shortenPath(effectiveParent, homeDir)}
            </span>
            <Button variant="secondary" size="sm" onclick={onBrowse}>
                {t('newagent.browse_folders')}
            </Button>
        </div>
        {#if inferredName}
            <span class="naw-path-hint" title={previewPath}>
                {t('newagent.project_folder_preview', { path: shortenPath(previewPath, homeDir) })}
            </span>
        {/if}
    </div>

    <Field
        label={t('newagent.clone_description_label')}
        placeholder={t('newagent.clone_description_placeholder')}
        bind:value={description}
        autocomplete="off"
        block
        onkeydown={onKeyDown}
    />

    <div class="naw-primary-cta">
        <Button variant="confirm" size="auto" onclick={onContinue}>
            <span class="naw-cta-inner">{t('newagent.continue_btn')}</span>
        </Button>
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

        .naw-section-label {
            color: var(--oc-text-muted);
            font-size: var(--oc-fs-micro);
            letter-spacing: var(--oc-tracking-caps);
            text-transform: uppercase;
        }

        .naw-path-group {
            display: flex;
            flex-direction: column;
            gap: var(--oc-space-1-5);
        }

        .naw-path-box {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: var(--oc-space-2);
            padding: var(--oc-space-1-5) var(--oc-space-2) var(--oc-space-1-5) var(--oc-space-3);
            border: var(--oc-border) solid var(--oc-line-panel);
            border-radius: var(--oc-radius-control);
            background: var(--oc-ground-field);
            min-width: 0;
        }

        .naw-path-value {
            color: var(--oc-text-primary);
            font-size: var(--oc-fs-body);
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            min-width: 0;
            flex: 1;
        }

        .naw-path-hint {
            color: var(--oc-text-muted);
            font-size: var(--oc-fs-label);
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .naw-primary-cta {
            display: flex;
            flex-direction: column;
            align-items: stretch;
            padding-top: var(--oc-space-1);
        }

        .naw-cta-inner {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-height: 28px;
            padding: var(--oc-space-1) var(--oc-space-2);
            font-size: var(--oc-fs-control);
        }
    }
</style>
