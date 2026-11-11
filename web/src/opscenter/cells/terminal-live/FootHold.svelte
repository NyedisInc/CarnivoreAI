<!-- no longer holds -->
<script lang="ts">
    import { sessions } from '../../api';
    import { rowFor } from '../terminal-viewer/meta';
    import { bannerItem, holdText, holds, startHoldFrames } from '../../../lib/budget-hold/hold-store.svelte';

    const { sessionId }: { sessionId: string } = $props();

    startHoldFrames();
    const item = $derived.by(() => {
        void holds.data;
        return bannerItem(sessionId, rowFor(sessions.data, sessionId)?.session_row_id);
    });
</script>

{#if item}
    <div class="oc-tf-hold" data-foot-hold role="status">{holdText(item)}</div>
{/if}

<style>
    @layer components {
        .oc-tf-hold {
            box-shadow: inset 0 1px 0 var(--oc-line-faint);
            padding: 0 var(--oc-space-2);
            font-family: var(--font-mono);
            font-size: var(--oc-fs-hint);
            line-height: 1.4;
            color: var(--oc-yellow);
            background: var(--oc-ground-titlerow);
            overflow-wrap: anywhere;
        }
    }
</style>
