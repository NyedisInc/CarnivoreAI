
<script lang="ts">
    import type { ReportAnswer, ReportFinding, ReportGate, ReportReview } from './admin.js';
    import DiffView from './DiffView.svelte';
    import { t } from './text.js';
    import { ADMIN_KEYS } from '../../../client/js/labels/admin.js';

    let { answer }: { answer: ReportAnswer } = $props();

    const report = $derived(answer.report || {});
    const gates = $derived<ReportGate[]>(
        [...(report.gates || [])].sort((a, b) => a.n - b.n),
    );
    const reviewGate = $derived(gates.find((gate) => gate.id === 'ai_review'));
    const review = $derived(report.review?.status === 'reviewed' ? report.review : undefined);
    const inventory = $derived(report.code_inventory);
    const clean = $derived(gates.find((gate) => gate.id === 'clean_room'));
    const others = $derived(gates.filter((gate) => gate !== reviewGate && gate !== clean));

    function findingText(f: ReportFinding): string {
        if (f.path && f.line) return t(ADMIN_KEYS.reportFindingAt, { path: f.path, line: f.line, detector: f.detector, code: f.code });
        if (f.path) return t(ADMIN_KEYS.reportFindingPath, { path: f.path, detector: f.detector, code: f.code });
        return t(ADMIN_KEYS.reportFindingBare, { detector: f.detector, code: f.code });
    }

    function warningText(warning: NonNullable<ReportReview['warnings']>[number]): string {
        const location = warning.file
            ? warning.line != null ? `${warning.file}:${warning.line}` : warning.file
            : t(ADMIN_KEYS.reportReviewNoLocation);
        return t(ADMIN_KEYS.reportReviewWarning, {
            kind: warning.kind, detail: warning.detail, location,
        });
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

    {#if inventory}
        <section class="admin-report__block">
            <h3 class="admin-report__heading">{t(ADMIN_KEYS.reportCodeHeading)}</h3>
            <p class="admin-list__name">{t(ADMIN_KEYS.reportCodeSummary, {
                count: inventory.file_count, bytes: inventory.total_bytes,
            })}</p>
            {#if inventory.files.length}
                <ul class="admin-report__list">
                    {#each inventory.files as file, index (index)}
                        <li class="admin-report__row">{t(ADMIN_KEYS.reportCodeFile, { path: file.path, bytes: file.bytes })}</li>
                    {/each}
                </ul>
            {/if}
            {#if inventory.truncated}
                <p class="admin-note">{t(ADMIN_KEYS.reportCodeTruncated)}</p>
            {/if}
        </section>
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
        {#if reviewGate}
            <p class="admin-list__name">
                {t(ADMIN_KEYS.reportReviewVerdict, { verdict: reviewGate.verdict, code: reviewGate.code })}
            </p>
        {/if}
        {#if review}
            <p class="admin-list__name">{t(ADMIN_KEYS.reportReviewResult, { verdict: review.verdict || '' })}</p>
            {#if review.summary}
                <p class="admin-report__row">{review.summary}</p>
            {/if}
            <p class="admin-list__meta">{t(ADMIN_KEYS.reportReviewSource, {
                model: review.model || '', at: review.reviewed_at || '',
            })}</p>
            {#if review.coverage}
                <p class="admin-list__meta">{t(
                    review.coverage.complete ? ADMIN_KEYS.reportReviewCoverageComplete : ADMIN_KEYS.reportReviewCoverageLimited,
                    { reviewed: review.coverage.reviewed_chars, total: review.coverage.total_chars,
                      text: review.coverage.text_files, omitted: review.coverage.omitted_files,
                      truncated: review.coverage.truncated_files, binary: review.coverage.binary_files },
                )}</p>
            {:else}
                <p class="admin-note">{t(ADMIN_KEYS.reportReviewCoverageUnknown)}</p>
            {/if}
            <p class="admin-report__label">{t(ADMIN_KEYS.reportReviewWarnings)}</p>
            {#if review.warnings?.length}
                <ul class="admin-report__list">
                    {#each review.warnings as warning, index (index)}
                        <li class="admin-report__row">{warningText(warning)}</li>
                    {/each}
                </ul>
            {:else if review.warnings}
                <p class="admin-note">{t(ADMIN_KEYS.reportReviewNoWarnings)}</p>
            {:else}
                <p class="admin-note">{t(ADMIN_KEYS.reportReviewWarningsUnknown)}</p>
            {/if}
        {:else}
            <p class="admin-note">{t(ADMIN_KEYS.reportReviewMissing)}</p>
            {#if reviewGate?.findings?.length}
                {@render findings(reviewGate.findings)}
            {/if}
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
