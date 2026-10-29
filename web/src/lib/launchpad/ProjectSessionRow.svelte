<!-- role="button" tabindex= -->
<script lang="ts">
    import SessionFace from '../sessions/SessionFace.svelte';
    import AgentFamilyPill from './AgentFamilyPill.svelte';
    import { t as reactiveT } from '../i18n/index.svelte';
    import {
        PROJECT_TREE_KEYS,
        workTitle,
    } from '../../../../client/js/labels/project-tree.js';
    import { SESSION_WORK_UNRECORDED_KEY, workAttrs } from './project-node';
    import type { TreeSessionRow } from './project-groups';
    import type { ProjectTreeHost } from './project-tree-host';
    import type { Translate } from '../sessions/types';

    interface Props {
        row: TreeSessionRow;
        workStamp?: string | null;
        transport?: string | null;
        host: ProjectTreeHost;
        t?: Translate;
    }

    let {
        row,
        workStamp = null,
        transport = null,
        host,
        t = reactiveT,
    }: Props = $props();

    const owned = $derived(!!row.created_by_cloude);
    const work = $derived(workAttrs(workStamp, SESSION_WORK_UNRECORDED_KEY));
    const displayName = $derived(host.displayLabel(row));

    async function open(): Promise<void> {
        if (row.is_active) {
            await host.returnToActive(row.session_id ?? null);
            return;
        }
        await host.attachSession(row.name);
    }

    function onKey(event: KeyboardEvent): void {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        event.preventDefault();
        void open();
    }
</script>

<div
    class="project-session-row"
    data-name={row.name}
    data-active={row.is_active ? '1' : '0'}
    data-work={work.state}
    data-work-at={work.at}
    role="button"
    tabindex="0"
    onclick={open}
    onkeydown={onKey}
>
    <SessionFace {row} {transport} name={displayName} nameClass="project-session-row__name" />
    <span class="badge {owned ? 'badge-tmux' : 'badge-external'}"
        >{owned ? t(PROJECT_TREE_KEYS.badgeTmux) : t(PROJECT_TREE_KEYS.badgeExternal)}</span
    >
    <AgentFamilyPill family={row.agent_family} source={row.agent_family_source} {t} />
</div>
