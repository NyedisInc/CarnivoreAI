<script lang="ts">
    import { onMount } from 'svelte';

    let enhanced = $state(false);
    let viewerConnected = $state(true);

    onMount(() => {
        enhanced = true;
    });
</script>

<section id="continuity" class="continuity" data-sc-act="pin" data-sc-span="1.25">
    <div class="continuity-stage tw:flex tw:flex-col tw:justify-center" data-sc-stage>
        <div class="continuity-inner tw:mx-auto tw:w-full">
            <div class="continuity-heading tw:flex tw:flex-col tw:gap-3">
                <h2>leave the desk.<br /><strong>keep the session.</strong></h2>
                <p>the browser is a view into the work. closing that view does not close the tmux session on your mac.</p>
            </div>

            <div class:viewer-away={!viewerConnected} class="continuity-machine" role="img" aria-label={viewerConnected ? 'Conceptual illustration: the agent runs in a tmux session on the Mac, and a phone viewer is connected.' : 'Conceptual illustration: the agent keeps running in a tmux session on the Mac while the phone viewer is disconnected.'}>
                <div class="machine-core tw:grid">
                    <div class="machine-node mac-node">
                        <span class="node-index">host</span>
                        <strong>your mac</strong>
                        <span>the machine doing the work</span>
                    </div>
                    <div class="machine-path" aria-hidden="true"><span class="path-trace"></span></div>
                    <div class="machine-node session-node">
                        <span class="node-index">persistent process</span>
                        <strong>tmux session</strong>
                        <span>agent and terminal stay here</span>
                    </div>
                </div>
                <div class="viewer-path tw:flex tw:items-center" aria-hidden="true">
                    <span class="viewer-wire"></span><span class="viewer-joint"></span>
                </div>
                <div class="viewer-node tw:flex tw:items-center tw:justify-between tw:gap-3">
                    <div class="tw:flex tw:flex-col">
                        <span class="node-index">remote view</span>
                        <strong>your phone</strong>
                    </div>
                    <span class="viewer-state">{viewerConnected ? 'connected' : 'away'}</span>
                </div>
            </div>

            <div class="continuity-foot tw:flex tw:flex-wrap tw:items-center tw:justify-between tw:gap-4">
                <p>conceptual illustration. the session path remains while the viewer comes and goes.</p>
                <p class="sr-only" role="status" aria-live="polite">{viewerConnected ? 'viewer connected; session stays on your mac.' : 'viewer disconnected; session stays on your mac.'}</p>
                {#if enhanced}
                    <button type="button" class="site-button site-button--quiet" onclick={() => viewerConnected = !viewerConnected}>
                        {viewerConnected ? 'leave the desk' : 'return to desk'}
                    </button>
                {/if}
            </div>
        </div>
    </div>
</section>
