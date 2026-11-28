
<script lang="ts">
    import { t as reactiveT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import Button from '../base/Button.svelte';
    import Field from '../base/Field.svelte';
    import { shortenPath } from './model';

    interface Props {
        folderPath: string;
        folderError: string;
        projectName: string;
        projectNameError: string;
        description: string;
        homeDir: string | null;
        onBrowse: () => void;
        onContinue: () => void;
        t?: Translate;
    }

    let {
        folderPath,
        folderError,
        projectName = $bindable(''),
        projectNameError,
        description = $bindable(''),
        homeDir,
        onBrowse,
        onContinue,
        t = reactiveT,
    }: Props = $props();

    function onKeyDown(e: KeyboardEvent): void {
        if (e.key === 'Enter') {
            e.preventDefault();
            onContinue();
        }
    }
</script>

<div class="naw-step">
    <h2 class="naw-heading">{t('newagent.open_folder_heading')}</h2>

    <div class="naw-path-group">
        <span class="naw-section-label">{t('newagent.open_folder_path_label')}</span>
        <div class="naw-path-box">
            <span class="naw-path-value" title={folderPath || t('newagent.open_folder_empty')}>
                {folderPath ? shortenPath(folderPath, homeDir) : t('newagent.open_folder_empty')}
            </span>
            <Button variant="secondary" size="sm" onclick={onBrowse}>
                {t('newagent.browse_folders')}
            </Button>
        </div>
        {#if folderError}
            <div class="naw-error" role="alert">{folderError}</div>
        {/if}
    </div>

    <Field
        label={t('newagent.project_name_label')}
        placeholder={t('newagent.project_name_placeholder')}
        bind:value={projectName}
        error={projectNameError || undefined}
        autocomplete="off"
        block
        onkeydown={onKeyDown}
    />

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

        .naw-error {
            padding: var(--oc-space-3);
            border: var(--oc-border) solid var(--oc-coral);
            border-radius: var(--oc-radius-control);
            background: color-mix(in oklab, var(--oc-coral) 14%, transparent);
            color: var(--oc-coral);
            font-size: var(--oc-fs-label);
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
