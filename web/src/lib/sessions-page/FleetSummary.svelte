
<script lang="ts">
    import Glyph from '../Glyph.svelte';
    import StatusLed from '../StatusLed.svelte';
    import type { Translate } from '../sessions/types';
    import type { FleetCounts } from './filters';

    interface Props {
        counts: FleetCounts;
        listingDown: boolean;
        historyFailed: boolean;
        t: Translate;
    }
    const { counts, listingDown, historyFailed, t }: Props = $props();
    const asleepLabel = $derived(t(historyFailed ? 'sessions.page.summary.asleep_failed' : 'sessions.page.summary.asleep'));
</script>

<div class="sp-sum" role="group" aria-label={t('sessions.page.summary.label')}>
    <span class="sp-pair" role="img" aria-label="{counts.running} {t('sessions.page.summary.running')}" title={t('sessions.page.summary.running')}>
        <Glyph name="terminal" size={14} /><b data-sum="running">{counts.running}</b>
    </span>
    {#if !listingDown}
        <span class="sp-pair" role="img" aria-label="{counts.needs} {t('sessions.page.summary.needs')}" title={t('sessions.page.summary.needs')}>
            <StatusLed status="question" size="14px" /><b data-sum="needs">{counts.needs}</b>
        </span>
        <span class="sp-pair" role="img" aria-label="{counts.working} {t('sessions.page.summary.working')}" title={t('sessions.page.summary.working')}>
            <StatusLed status="working" size="14px" /><b data-sum="working">{counts.working}</b>
        </span>
    {/if}
    <span class="sp-pair" role="img" aria-label="{historyFailed ? '?' : counts.asleep} {asleepLabel}" title={asleepLabel}>
        <StatusLed status="asleep" size="14px" /><b data-sum="asleep">{historyFailed ? '?' : counts.asleep}</b>
    </span>
    {#if counts.oldestDays > 0}
        <span class="sp-pair" role="img" aria-label="{counts.oldestDays}d {t('sessions.page.summary.oldest')}" title={t('sessions.page.summary.oldest')}>
            <Glyph name="clock" size={14} /><b data-sum="oldest">{counts.oldestDays}d</b>
        </span>
    {/if}
</div>
