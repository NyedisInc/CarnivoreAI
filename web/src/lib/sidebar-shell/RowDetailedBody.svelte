
<script lang="ts">
    import Icon from '../../opscenter/ui/Icon.svelte';
    import LimitGauge from '../../opscenter/ui/LimitGauge.svelte';
    import RowLiveWork from './RowLiveWork.svelte';
    import type { RowBodyPlan } from './row-body';
    import RowActions from './RowActions.svelte';
    import type { ContextPlan } from './row-context';
    import type { RowChipSpec } from './row-plan';

    let { body, actions, context = null }: { body: RowBodyPlan; actions: RowChipSpec[]; context?: ContextPlan | null } = $props();
</script>

<div class="session-row-body session-row-body--detailed">{#each body.flags as f (f.kind)}<div class="session-row-body__line session-row-body__flag" data-flag={f.kind} data-tone={f.tone}><span class="session-row-body__flag-words">{f.text}</span>{#if f.kind === 'exited'}<RowActions {actions} />{/if}</div>{/each}{#if !body.ended}<div class="session-row-body__line session-row-body__foot"><RowLiveWork parts={body.live} none={body.noLiveWork} />{#if context}<span class="session-row-body__ctx" title={context.label}><Icon name="gauge" size={11} /><LimitGauge class="session-row-body__ctx-bar" variant="fill" pct={context.pct} scale={context.scale} meterText={context.label} height={4} ariaHidden /><span class="session-row-body__ctx-pct">{Math.round(context.pct)}%</span></span>{/if}</div>{/if}</div>
