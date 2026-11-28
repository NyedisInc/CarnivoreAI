
<script lang="ts">
    import { t } from '../i18n/index.svelte';
    import RowLiveWork from './RowLiveWork.svelte';
    import type { RowBodyPlan } from './row-body';
    import RowActions from './RowActions.svelte';
    import type { RowChipSpec } from './row-plan';

    let { body, actions }: { body: RowBodyPlan; actions: RowChipSpec[] } = $props();
</script>

<div class="session-row-body session-row-body--cozy">{#if body.ended}<span class="session-row-body__ended" data-tone={body.ended.tone}>{body.ended.text}</span>{#if body.ended.dead}<RowActions {actions} />{/if}{:else}<span class="session-row-body__status-line">{#if body.statusWord}<span class="session-row-body__state" data-tone={body.statusWord.tone}>{body.statusWord.text}</span>{/if}{#if body.modelName}{#if body.statusWord}<span class="session-row-body__sep" aria-hidden="true"> · </span>{/if}<span class="session-row-body__model">{body.modelName}</span>{/if}{#if body.effort}<span class="session-row-body__sep" aria-hidden="true"> · </span><span class="session-row-body__effort"><span class="oc-visually-hidden">{t('sidebar.row.effort.prefix')}</span>{' '}{body.effort}</span>{/if}</span>{#if body.mode === 'cozy' && body.live.length}<RowLiveWork parts={body.live} none={false} />{/if}{#if body.when}<span class="session-row-body__when">{body.when}</span>{/if}{/if}</div>
