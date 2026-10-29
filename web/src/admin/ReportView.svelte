
<script lang="ts">
    import type { ReportAnswer, ReportFinding, ReportGate } from './admin.js';
    import DiffView from './DiffView.svelte';
    import { t } from './text.js';
    import { ADMIN_KEYS } from '../../../client/js/labels/admin.js';

    let { answer }: { answer: ReportAnswer } = $props();

    const report = $derived(answer.report || {});
    const gates = $derived<ReportGate[]>(
        [...(report.gates || [])].sort((a, b) => a.n - b.n),
    );
    const review = $derived(gates.find((gate) => gate.id === 'ai_review'));
    const clean = $derived(gates.find((gate) => gate.id === 'clean_room'));
    const others = $derived(gates.filter((gate) => gate !== review && gate !== clean));

    function findingText(f: ReportFinding): string {
        if (f.path && f.line) return t(ADMIN_KEYS.reportFindingAt, { path: f.path, line: f.line, detector: f.detector, code: f.code });
        if (f.path) return t(ADMIN_KEYS.reportFindingPath, { path: f.path, detector: f.detector, code: f.code });
        return t(ADMIN_KEYS.reportFindingBare, { detector: f.detector, code: f.code });
    }
</script>

{#snippet findings(list: ReportFinding[] | undefined)}
    {#if list && list.length}
        <ul class="admin-report__list">
            {#each list as f, index (index)}
                <li class="admin-report__row">{findingText(f)}</li>
            {/each}
        </ul>
    {:else}
        <p class="admin-note">{t(ADMIN_KEYS.reportNoFindings)}</p>
    {/if}
{/snippet}

<section class="admin-report">
    <h3 class="admin-report__heading">{t(ADMIN_KEYS.reportHeading)}</h3>
    <p class="admin-list__meta">{t(ADMIN_KEYS.reportOutcome, { outcome: report.outcome || answer.gate_state })}</p>
    <p class="admin-list__meta">{t(ADMIN_KEYS.reportDigest, { sha: (answer.report_sha256 || '').slice(0, 12) })}</p>
    {#if report.app_sha}
        <p class="admin-list__meta">{t(ADMIN_KEYS.reportAppSha, { sha: report.app_sha.slice(0, 12) })}</p>
    {/if}
    {#if report.grade}
        <p class="admin-list__meta">{t(ADMIN_KEYS.reportGrade, { grade: report.grade })}</p>
    {/if}

    <section class="admin-report__block">
        <h3 class="admin-report__heading">{t(ADMIN_KEYS.reportGatesHeading)}</h3>
        {#each others as gate (gate.n)}
            <div class="admin-report__gate admin-report__gate--{gate.verdict}">
                <p class="admin-list__name">
                    {t(ADMIN_KEYS.reportGate, { n: gate.n, id: gate.id, verdict: gate.verdict, code: gate.code })}
                </p>
                {#if gate.findings && gate.findings.length}
                    {@render findings(gate.findings)}
                {/if}
            </div>
        {/each}
    </section>

    <section class="admin-report__block">
        <h3 class="admin-report__heading">{t(ADMIN_KEYS.reportReviewHeading)}</h3>
        {#if review}
            <p class="admin-list__name">
                {t(ADMIN_KEYS.reportReviewVerdict, { verdict: review.verdict, code: review.code })}
            </p>
            <p class="admin-report__label">{t(ADMIN_KEYS.reportReviewWarnings)}</p>
            {@render findings(review.findings)}
        {:else}
            <p class="admin-note">{t(ADMIN_KEYS.reportNotRun)}</p>
        {/if}
    </section>

    <section class="admin-report__block">
        <h3 class="admin-report__heading">{t(ADMIN_KEYS.reportCleanHeading)}</h3>
        {#if clean}
            <p class="admin-list__name">
                {t(ADMIN_KEYS.reportCleanVerdict, { verdict: clean.verdict, code: clean.code })}
            </p>
            {@render findings(clean.findings)}
        {:else}
            <p class="admin-note">{t(ADMIN_KEYS.reportNotRun)}</p>
        {/if}
    </section>

    <DiffView diff={report.diff} />
</section>
