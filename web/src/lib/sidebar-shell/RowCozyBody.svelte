
<script lang="ts">
    import { t } from '../i18n/index.svelte';
    import RowLiveWork from './RowLiveWork.svelte';
    import ModelMark from './ModelMark.svelte';
    import type { RowBodyPlan } from './row-body';
    import RowActions from './RowActions.svelte';
    import type { RowChipSpec } from './row-plan';

    let { body, actions }: { body: RowBodyPlan; actions: RowChipSpec[] } = $props();
</script>

<div class="session-row-body session-row-body--cozy">{#if body.ended}<span class="session-row-body__ended" data-tone={body.ended.tone}>{body.ended.text}</span>{#if body.ended.dead}<RowActions {actions} />{/if}{:else}{#if body.model}<ModelMark model={body.model} /><span class="session-row-body__model">{body.modelName}</span>{/if}{#if body.live.length}<RowLiveWork parts={body.live} none={false} />{/if}{#if body.model && body.effort}<span class="session-row-body__effort"><span class="oc-visually-hidden">{t('sidebar.row.effort.prefix')}</span>{' '}{body.effort}</span>{/if}{/if}</div>
