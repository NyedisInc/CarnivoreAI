
<script lang="ts">
    import { Button as BaseButton } from '../base';
    import { errorCode } from './api';
    import { useRender } from './context';
    import type { UiNode } from './validate';

    const { node }: { node: Extract<UiNode, { type: 'button' }> } = $props();
    const ctx = useRender();
    let asking = $state(false);
    let busy = $state(false);
    let line = $state<string | null>(null);
    const unavailable = $derived(node.action.call !== 'route');

    async function go(): Promise<void> {
        if (busy || unavailable) return;
        if (node.confirm && !asking) {
            asking = true;
            return;
        }
        asking = false;
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

<div class="cu-action" data-cu="button">
    {#if asking}
        <span class="cu-action__ask">{node.confirm}</span>
        <BaseButton variant={node.tone === 'danger' ? 'danger' : 'confirm'} onclick={go} disabled={busy}>{ctx.t('cplug_ui.confirm_yes')}</BaseButton>
        <BaseButton onclick={() => (asking = false)}>{ctx.t('cplug_ui.confirm_no')}</BaseButton>
    {:else}
        <BaseButton variant={node.tone === 'danger' ? 'danger' : 'secondary'} onclick={go} disabled={busy || unavailable}>{node.label}</BaseButton>
    {/if}
    {#if line}<span class="cu-action__line" role="status">{line}</span>{/if}
</div>
