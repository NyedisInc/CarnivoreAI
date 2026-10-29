<!-- a dialog is open -->
<script lang="ts">
    import Button from '../base/Button.svelte';
    import '../projects-shared/projects-shared.css';
    import AnchoredPopup from '../dialog-frame/AnchoredPopup.svelte';
    import type { Translate } from '../sessions/types';
    import ProjectTransport from '../pack-transport/ProjectTransport.svelte';
    import { ageFormatter } from '../projects-shared/format';
    import { previewOf } from '../projects-shared/ledger-model';
    import { projectPanels, type PanelReadState } from '../../cplugs/sdk/project-panels';
    import { openModalCount } from '../modal';
    import type { ProjectTool } from './project-tools';

    interface Props {
        tool: ProjectTool;
        project: { id: number; name: string };
        t: Translate;
        onClose: () => void;
    }
    const { tool, project, t, onClose }: Props = $props();

    const panel = $derived(tool.kind === 'panel' ? (projectPanels().find((p) => p.id === tool.panelId) ?? null) : null);
    const Panel = $derived(panel?.component);
    const age = $derived(ageFormatter(t, () => Date.now()));
    const title = $derived(
        tool.kind === 'settings'
            ? t('sessions.page.tool.settings_title', { name: project.name })
            : t('sessions.page.tool.panel_title', { panel: panel ? t(panel.labelKey) : '', name: project.name }),
    );

    function tally(count: number, read: PanelReadState): string {
        if (read === 'loading') return t('projects.page.group.reading');
        if (read === 'failed') return t('projects.page.group.unread');
        return count ? String(count) : t('projects.page.group.none');
    }
</script>


<AnchoredPopup class="pw" tabindex={-1} label={title} data-project-tool={tool.kind === 'panel' ? tool.panelId : 'settings'}
    placement="manual" initialFocus="self" dismissable={() => openModalCount() === 0} {onClose}>
    <div class="pw-title">
        <span class="pw-label">{title}</span>
        <Button size="sm" data-project-tool-close onclick={onClose}>{t('sessions.page.tool.close')}</Button>
    </div>
    <div class="pw-body ph-page">
        {#if tool.kind === 'settings'}
            <ProjectTransport name={project.name} startOpen />
        {:else if Panel}
            {#snippet header(count: number, read: PanelReadState)}
                <div class="pw-tally" data-project-tool-tally>{tally(count, read)}</div>
            {/snippet}
            <div class="ph-table">
                <Panel projectId={project.id} projectKey={String(project.id)} {header} isFolded={() => false} {age} {previewOf} />
            </div>
        {/if}
    </div>
</AnchoredPopup>

<style>
    @layer components {
        :global(.pw[data-project-tool]) {
            position: fixed;
            z-index: 9000;
            inset: 12vh auto auto 50%;
            transform: translateX(-50%);
            margin: 0;
            width: min(760px, calc(100vw - 16px));
            max-height: 76vh;
            display: flex;
            flex-direction: column;
            box-sizing: border-box;
            color: var(--oc-text-primary);
            overflow: hidden;
        }

        .pw-title {
            flex: none;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: var(--oc-space-2);
            min-height: 30px;
            padding: 0 var(--oc-space-3);
            background: var(--oc-ground-titlerow);
            box-shadow: inset 0 -1px 0 var(--oc-line-faint);
        }

        .pw-label {
            min-width: 0;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            font-family: var(--font-mono);
            font-size: var(--oc-fs-label, 11px);
            letter-spacing: var(--oc-tracking-label, 0.6px);
            text-transform: uppercase;
            color: var(--oc-orange);
        }

        .pw-body {
            flex: 1 1 auto;
            min-height: 0;
            overflow: auto;
            padding: var(--oc-space-2) 0;
        }

        .pw-tally {
            padding: 0 var(--oc-space-3);
            font-size: var(--oc-fs-micro, 10px);
            letter-spacing: var(--oc-tracking-label, 0.6px);
            text-transform: uppercase;
            color: var(--oc-text-dim);
        }
    }
</style>
