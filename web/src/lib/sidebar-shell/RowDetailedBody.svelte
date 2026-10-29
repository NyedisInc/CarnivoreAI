
<script lang="ts">
    import RowLiveWork from './RowLiveWork.svelte';
    import type { RowBodyPlan } from './row-body';
    import RowActions from './RowActions.svelte';
    import type { RowChipSpec } from './row-plan';

    let { body, actions }: { body: RowBodyPlan; actions: RowChipSpec[] } = $props();
</script>

<div class="session-row-body session-row-body--detailed">{#each body.flags as f (f.kind)}<div class="session-row-body__line session-row-body__flag" data-flag={f.kind} data-tone={f.tone}><span class="session-row-body__flag-words">{f.text}</span>{#if f.kind === 'exited'}<RowActions {actions} />{/if}</div>{/each}{#if body.ended && !body.ended.dead}<div class="session-row-body__line"><span class="session-row-body__ended" data-tone={body.ended.tone}>{body.ended.text}</span></div>{/if}{#if !body.ended}<div class="session-row-body__line session-row-body__foot"><RowLiveWork parts={body.live} none={body.noLiveWork} />{#if body.when}<span class="session-row-body__when">{body.when}</span>{/if}</div>{/if}</div>
