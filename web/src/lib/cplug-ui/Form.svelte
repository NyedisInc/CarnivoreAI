
<script lang="ts">
    import { Button } from '../base';
    import { errorCode } from './api';
    import { useRender } from './context';
    import { provideForm } from './form-context';
    import Node from './Node.svelte';
    import type { UiNode } from './validate';

    const { node }: { node: Extract<UiNode, { type: 'form' }> } = $props();
    const ctx = useRender();
    const form = provideForm();
    let busy = $state(false);
    let line = $state<string | null>(null);
    const unavailable = $derived(node.action.call !== 'route' && node.action.call !== 'tool');

    async function submit(event: SubmitEvent): Promise<void> {
        event.preventDefault();
        event.stopPropagation();
        if (busy || unavailable) return;
        if (!form.validateAll()) return;
        busy = true;
        line = null;
        try {
            await ctx.run({
                ...node.action,
                payload: { ...(node.action.payload ?? {}), ...form.snapshot() },
            });
        } catch (error) {
            line = ctx.t(errorCode(error) === 'cplug_not_running' ? 'cplug_ui.not_running' : 'cplug_ui.action_failed');
        } finally {
            busy = false;
        }
    }
</script>

<form class="cu-form" data-cu="form" data-tone={node.tone ?? 'normal'} onsubmit={submit} novalidate>
    {#each node.children as child}<Node node={child} />{/each}
    <div class="cu-form__actions">
        <Button type="submit" variant={node.tone === 'danger' ? 'danger' : 'confirm'} disabled={busy || unavailable}>
            {node.submit_label ?? ctx.t('cplug_ui.form_submit')}
        </Button>
        {#if line}<span class="cu-form__line" role="status">{line}</span>{/if}
    </div>
</form>
