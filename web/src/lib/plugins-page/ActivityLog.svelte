
<script lang="ts">
    import type { Translate } from '../sessions/types';
    import type { ActivityRow } from './cplugs-adapter';

    interface Props {
        load: () => Promise<ActivityRow[]>;
        t: Translate;
    }

    const { load, t }: Props = $props();

    let rows = $state<ActivityRow[] | null>(null);
    let failed = $state(false);

    // svelte-ignore state_referenced_locally
    load().then(
        (got) => (rows = got),
        () => (failed = true),
    );

    function clock(ts: number): string {
        return new Date(ts * 1000).toTimeString().slice(0, 8);
    }
</script>

<section class="plp-region" data-perm-log aria-label={t('plugins.page.activity.title')}>
    <h3 class="pl-label">{t('plugins.page.activity.title')}</h3>
    {#if failed}
        <p class="plp-note">{t('plugins.page.activity.failed')}</p>
    {:else if rows === null}
        <p class="plp-note">{t('plugins.page.activity.loading')}</p>
    {:else if rows.length === 0}
        <p class="plp-note">{t('plugins.page.activity.empty')}</p>
    {:else}
        <ul class="plp-log">
            {#each rows as row, i (i)}
                <li class="plp-log__row" data-perm-log-row class:plp-log__row--error={row.status !== 'ok'}>
                    <span class="plp-log__time">{clock(row.ts)}</span>
                    <span>{row.method}</span>
                    <span class="plp-dim">{row.permission}</span>
                    {#if row.target}<span>{row.target}</span>{/if}
                    <span>{row.status}{row.count > 1 ? ` x${row.count}` : ''}</span>
                </li>
            {/each}
        </ul>
    {/if}
</section>
