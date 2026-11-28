
<script lang="ts">
    import { t as reactiveT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import Button from '../base/Button.svelte';
    import Icon from '../../opscenter/ui/Icon.svelte';

    interface Props {
        onEmpty: () => void;
        onClone: () => void;
        onOpenFolder: () => void;
        t?: Translate;
    }

    let { onEmpty, onClone, onOpenFolder, t = reactiveT }: Props = $props();
</script>

<div class="naw-step">
    <h2 class="naw-heading">{t('newagent.project_kind_heading')}</h2>

    <div class="naw-choice-list">
        <div class="naw-choice-item">
            <Button variant="secondary" size="auto" onclick={onEmpty}>
                <span class="naw-choice-inner">
                    <span class="naw-choice-icon"><Icon name="folder-plus" size={14} /></span>
                    <span class="naw-choice-copy">
                        <span class="naw-choice-title">{t('newagent.kind_empty')}</span>
                        <span class="naw-choice-sub">{t('newagent.kind_empty_sub')}</span>
                    </span>
                    <span class="naw-choice-arrow"><Icon name="chevron-right" size={13} /></span>
                </span>
            </Button>
        </div>

        <div class="naw-choice-item">
            <Button variant="secondary" size="auto" onclick={onClone}>
                <span class="naw-choice-inner">
                    <span class="naw-choice-icon"><Icon name="branch" size={14} /></span>
                    <span class="naw-choice-copy">
                        <span class="naw-choice-title">{t('newagent.kind_clone')}</span>
                        <span class="naw-choice-sub">{t('newagent.kind_clone_sub')}</span>
                    </span>
                    <span class="naw-choice-arrow"><Icon name="chevron-right" size={13} /></span>
                </span>
            </Button>
        </div>

        <div class="naw-choice-item">
            <Button variant="secondary" size="auto" onclick={onOpenFolder}>
                <span class="naw-choice-inner">
                    <span class="naw-choice-icon"><Icon name="folder" size={14} /></span>
                    <span class="naw-choice-copy">
                        <span class="naw-choice-title">{t('newagent.kind_folder')}</span>
                        <span class="naw-choice-sub">{t('newagent.kind_folder_sub')}</span>
                    </span>
                    <span class="naw-choice-arrow"><Icon name="chevron-right" size={13} /></span>
                </span>
            </Button>
        </div>
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

        .naw-choice-list {
            display: flex;
            flex-direction: column;
            gap: var(--oc-space-3);
        }

        .naw-choice-item {
            display: flex;
            flex-direction: column;
            align-items: stretch;
        }

        .naw-choice-inner {
            width: 100%;
            display: flex;
            align-items: center;
            gap: var(--oc-space-3);
            padding: var(--oc-space-2) var(--oc-space-1);
            text-align: left;
            min-width: 0;
        }

        .naw-choice-icon {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 28px;
            height: 28px;
            border: var(--oc-border) solid var(--oc-line-panel);
            border-radius: var(--oc-radius-control);
            background: var(--oc-ground-field);
            color: var(--oc-text-secondary);
            flex-shrink: 0;
        }

        .naw-choice-copy {
            display: flex;
            flex-direction: column;
            gap: var(--oc-space-0-5);
            flex: 1;
            min-width: 0;
        }

        .naw-choice-title {
            color: var(--oc-text-bright);
            font-size: var(--oc-fs-run-title);
            line-height: var(--oc-lh-tight);
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .naw-choice-sub {
            color: var(--oc-text-secondary);
            font-size: var(--oc-fs-label);
            font-weight: normal;
            line-height: var(--oc-lh-body);
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .naw-choice-arrow {
            color: var(--oc-text-muted);
            display: inline-flex;
            align-items: center;
            flex-shrink: 0;
        }
    }
</style>
