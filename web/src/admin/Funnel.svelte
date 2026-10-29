
<script lang="ts">
    import { ApiRefusal, refusalMessage, type AdminApi, type Refusal } from './admin.js';
    import { funnelDays, stepTotal, totalsBySource, type FunnelDay } from './funnel.js';
    import { t } from './text.js';
    import { ADMIN_KEYS } from '../../../client/js/labels/admin.js';

    let { api }: { api: AdminApi } = $props();

    let days = $state<FunnelDay[]>([]);
    let loaded = $state(false);
    let refusal = $state<Refusal | null>(null);

    $effect(() => {
        void (async () => {
            try {
                days = await funnelDays(api, 30);
            } catch (error) {
                if (!(error instanceof ApiRefusal)) throw error;
                refusal = error.refusal;
            }
            loaded = true;
        })();
    });

    const totals = $derived(totalsBySource(days));
    const refusalText = $derived(refusalMessage(refusal, t));
</script>

<section class="admin-panel">
    <h2 class="admin-panel__heading">{t(ADMIN_KEYS.funnelHeading)}</h2>

    {#if refusalText}
        <p class="admin-refusal" role="alert">{refusalText}</p>
    {/if}

    {#if !loaded}
        <p class="admin-note">{t(ADMIN_KEYS.loading)}</p>
    {:else if days.length === 0}
        <p class="admin-note">{t(ADMIN_KEYS.funnelEmpty)}</p>
    {:else}
        <h3 class="admin-list__name">{t(ADMIN_KEYS.funnelTotals)}</h3>
        <table class="admin-table">
            <thead>
                <tr>
                    <th scope="col">{t(ADMIN_KEYS.funnelColumnSource)}</th>
                    <th scope="col">{t(ADMIN_KEYS.funnelColumnProvider)}</th>
                    <th scope="col">{t(ADMIN_KEYS.funnelStart)}</th>
                    <th scope="col">{t(ADMIN_KEYS.funnelProof)}</th>
                    <th scope="col">{t(ADMIN_KEYS.funnelDone)}</th>
                </tr>
            </thead>
            <tbody>
                {#each totals as row (row.source + '/' + row.provider)}
                    <tr>
                        <td>{row.source}</td>
                        <td>{row.provider}</td>
                        <td>{row.start}</td>
                        <td>{row.proof}</td>
                        <td>{row.done}</td>
                    </tr>
                {/each}
            </tbody>
        </table>

        <h3 class="admin-list__name">{t(ADMIN_KEYS.funnelByDay)}</h3>
        <table class="admin-table">
            <thead>
                <tr>
                    <th scope="col">{t(ADMIN_KEYS.funnelColumnDay)}</th>
                    <th scope="col">{t(ADMIN_KEYS.funnelStart)}</th>
                    <th scope="col">{t(ADMIN_KEYS.funnelProof)}</th>
                    <th scope="col">{t(ADMIN_KEYS.funnelDone)}</th>
                </tr>
            </thead>
            <tbody>
                {#each days as day (day.date)}
                    <tr>
                        <td>{day.date}</td>
                        <td>{stepTotal(day.start)}</td>
                        <td>{stepTotal(day.proof)}</td>
                        <td>{stepTotal(day.done)}</td>
                    </tr>
                {/each}
            </tbody>
        </table>
    {/if}
</section>
