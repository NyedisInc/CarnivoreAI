
<script lang="ts">
    import { t as reactiveT } from '../i18n/index.svelte';
    import {
        attentionReason,
        attentionTitle,
        PROJECT_TREE_KEYS,
    } from '../../../../client/js/labels/project-tree.js';
    import { rowKey, type AttentionItem } from './project-groups';
    import type { ProjectTreeHost } from './project-tree-host';
    import type { Translate } from '../sessions/types';

    interface Props {
        items: AttentionItem[];
        host: ProjectTreeHost;
        t?: Translate;
    }

    let { items, host, t = reactiveT }: Props = $props();
</script>

{#if items.length > 0}
    <div
        class={['project-node', 'project-node--attention']}
        data-project-node="needs-attention"
        role="status"
    >
        <div class={['project-node__header', 'project-node__header--attention']}>
            <span class="project-node__attention-head"
                >{t(PROJECT_TREE_KEYS.attentionHead)}</span
            >
            <span class="project-node__title">{attentionTitle(items.length, t)}</span>
        </div>
        <div class="project-node__sessions">
            {#each items as item (rowKey(item.session))}
                <div
                    class={['project-session-row', 'project-session-row--attention']}
                    data-name={item.session.name}
                >
                    <span class="project-session-row__name"
                        >{host.displayLabel(item.session)}</span
                    >
                    <span class="project-session-row__attention-reason"
                        >{attentionReason(item, t)}</span
                    >
                </div>
            {/each}
        </div>
    </div>
{/if}
