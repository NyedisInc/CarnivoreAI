
<script lang="ts">
    import { Button, State } from '../base';
    import { errorCode } from './api';
    import { useRender } from './context';
    import type { UiNode } from './validate';

    const { node }: { node: Extract<UiNode, { type: 'empty_state' }> } = $props();
    const ctx = useRender();
    const kind = $derived(node.tone === 'warn' ? 'warn' : node.tone === 'danger' ? 'error' : 'empty');
    let busy = $state(false);
    let line = $state<string | null>(null);
    const unavailable = $derived(node.action ? node.action.call !== 'route' && node.action.call !== 'tool' : true);

    async function go(): Promise<void> {
        if (!node.action || busy || unavailable) return;
        busy = true;
        line = null;
        try {
            await ctx.run(node.action);
        } catch (error) {
            line = ctx.t(errorCode(error) === 'cplug_not_running' ? 'cplug_ui.not_running' : 'cplug_ui.action_failed');
        } finally {
            busy = false;
        }
    }
</script>

{#snippet actionSlot()}
    {#if node.action}
        <Button size="sm" variant={node.tone === 'danger' ? 'danger' : 'secondary'} onclick={go} disabled={busy || unavailable}>
            {ctx.t('cplug_ui.empty_action')}
        </Button>
        {#if line}<span class="cu-action__line" role="status">{line}</span>{/if}
    {/if}
{/snippet}

<div class="cu-empty" data-cu="empty_state" data-tone={node.tone ?? 'normal'}>
    <State {kind} title={node.title} hint={node.description} actions={node.action ? actionSlot : undefined} />
</div>
