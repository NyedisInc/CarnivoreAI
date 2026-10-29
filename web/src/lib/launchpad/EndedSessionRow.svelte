<!-- hidden  role="button" -->
<script lang="ts">
    import Button from '../base/Button.svelte';
    import SessionFace from '../sessions/SessionFace.svelte';
    import AgentFamilyPill from './AgentFamilyPill.svelte';
    import { t as reactiveT } from '../i18n/index.svelte';
    import { PROJECT_TREE_KEYS } from '../../../../client/js/labels/project-tree.js';
    import { RECENT_KEYS } from '../../../../client/js/labels/recent-session.js';
    import type { TreeSessionRow } from './project-groups';
    import type { ProjectTreeHost } from './project-tree-host';
    import type { Translate } from '../sessions/types';

    interface Props {
        row: TreeSessionRow;
        host: ProjectTreeHost;
        t?: Translate;
    }

    let { row, host, t = reactiveT }: Props = $props();

    const owned = $derived(!!row.created_by_cloude);
    const uuid = $derived(row.session_uuid || '');
    const displayName = $derived(host.displayLabel(row));
</script>

<div
    class={['project-session-row', 'project-session-row--ended']}
    data-name={row.name}
    data-ended="1"
    data-lifecycle="stopped"
    data-uuid={uuid}
>
    
    <SessionFace {row} lifecycle="stopped" name={displayName} nameClass="project-session-row__name" />
    <span class={['badge', 'badge-ended']}>{t(PROJECT_TREE_KEYS.badgeEnded)}</span>
    <span class="badge {owned ? 'badge-tmux' : 'badge-external'}"
        >{owned ? t(PROJECT_TREE_KEYS.badgeTmux) : t(PROJECT_TREE_KEYS.badgeExternal)}</span
    >
    <AgentFamilyPill family={row.agent_family} source={row.agent_family_source} {t} />
    <Button
        variant="confirm"
        size="sm"
        data-record-action="restart"
        data-uuid={uuid}
        onclick={() => host.restartEnded(row)}>{t(RECENT_KEYS.restartAction)}</Button
    >
    <Button
        size="sm"
        data-record-action="archive"
        data-uuid={uuid}
        title={t(RECENT_KEYS.archiveActionTitle)}
        aria-label={t(RECENT_KEYS.archiveActionAria)}
        onclick={() => host.archiveRecord(uuid)}>{t(RECENT_KEYS.archiveAction)}</Button
    >
</div>
