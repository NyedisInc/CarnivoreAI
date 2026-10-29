
<script lang="ts">
    import Icon from '../../opscenter/ui/Icon.svelte';
    import { cleanRoomSkipExpected } from './kinds';
    import { bytesText, clockText, dateText, groupedNumber } from './format';
    import Ident from './Ident.svelte';
    import Panel from './Panel.svelte';
    import type { PageProps } from './props';
    import { storedFacts, storedRows } from './checks-model';
    import type { CheckEntry, LocalCheck } from './types';
    import './checks.css';

    const { store, t }: PageProps = $props();

    const loc = $derived(store.sel ?? '');
    const stepN = $derived.by((): number | null => {
        const n = /^chk(\d+):/.exec(store.mid?.ev ?? '');
        return n ? Number(n[1]) : null;
    });
    const stored = $derived(stepN === null ? undefined : store.facts[loc]?.checks[stepN]);
    const live = $derived.by((): CheckEntry | null => {
        const visit = store.checks[loc];
        return stored && stepN === 0 && visit?.preview && visit.version === stored.version ? visit : null;
    });
    const record = $derived.by((): LocalCheck | undefined => {
        if (live) return undefined;
        return stored ?? (stepN === null && !store.checks[loc] ? store.facts[loc]?.checks[0] : undefined);
    });
    const entry = $derived.by((): CheckEntry | null =>
        record ? { version: record.version, ok: record.ok, at: record.at, summary: record.summary, preview: null } : live ?? store.checkOf(loc),
    );
    const kept = $derived(record ? storedFacts(record) : null);
    const keptGrade = $derived(kept?.grade ?? '');
    const keptNote = $derived(keptGrade ? t(`publish.page.grade.${keptGrade === 'a' || keptGrade === 'A' ? 'a' : keptGrade === 'b' || keptGrade === 'B' ? 'b' : 'c'}`) : '');
    const pv = $derived(entry?.preview ?? null);
    const keptRows = $derived(!entry?.ok && !pv && record ? storedRows(record) : []);
    const kind = $derived(pv?.kind ?? store.folders?.find((f) => f.location === loc)?.kind);
    const grade = $derived(pv?.lint?.grade ?? '');
    const gradeNote = $derived(grade ? t(`publish.page.grade.${grade === 'a' || grade === 'A' ? 'a' : grade === 'b' || grade === 'B' ? 'b' : 'c'}`) : '');
    const notes = $derived((pv?.lint?.failed ?? []).map((f) => t('skill.publish.lint.failure', { rule: f.rule ?? '', detail: f.detail ?? '' })).join('; '));
    const title = $derived.by((): string => {
        if (!entry) return '';
        if (entry.ok) {
            const count = pv?.lint?.failed?.length ?? 0;
            return count > 0 ? t('publish.page.timeline.check_notes.title', { version: entry.version, count }) : t('publish.page.timeline.check_clean.title', { version: entry.version });
        }
        const codes = pv ? (pv.refusals ?? []).map((r) => r.code).join(', ') : entry.summary;
        return t('publish.page.timeline.check_failed.title', { version: entry.version, codes });
    });
</script>

<div class="pp-ck" data-pp="LocalCheckView">
    {#if entry}
        <h2 class="d-name pp-ident"><Ident text={title} /></h2>
        <p class="d-kind">
            <span>{t('publish.page.local.run_on', { date: dateText(entry.at, t), time: clockText(entry.at, t) })}</span>
            <span>{t('publish.page.local.nothing_sent')}</span>
        </p>
        <Panel label={t('publish.page.local.this_check')}>
            <p class="d-lead d-lead--first">{t('publish.page.local.this_check_lead')}</p>
            {#if pv}
                <dl class="d-facts">
                    <div><dt>{t('publish.page.fact.grade')}</dt><dd>{grade ? t('publish.page.fact.grade_value', { grade, note: gradeNote }) : t('publish.page.fact.grade_none')}</dd></div>
                    <div><dt>{t('publish.page.fact.files')}</dt><dd>{t('publish.page.fact.files_value', { count: pv.file_count ?? 0, bytes: groupedNumber(pv.total_bytes ?? 0) })}</dd></div>
                    {#if pv.cost?.description_tokens_est}<div><dt>{t('publish.page.fact.listing_cost')}</dt><dd>{t('publish.page.local.cost_value', { tokens: pv.cost.description_tokens_est })}</dd></div>{/if}
                </dl>
            {:else if kept}
                <dl class="d-facts">
                    <div><dt>{t('publish.page.fact.grade')}</dt><dd>{keptGrade ? t('publish.page.fact.grade_value', { grade: keptGrade, note: keptNote }) : t('publish.page.fact.grade_none')}</dd></div>
                    {#if kept.files !== null}<div><dt>{t('publish.page.fact.files')}</dt><dd>{t('publish.page.fact.files_value', { count: kept.files, bytes: groupedNumber(kept.bytes ?? 0) })}</dd></div>{/if}
                </dl>
            {/if}
        </Panel>
        {#if !entry.ok && pv?.refusals?.length}
            <Panel label={t('publish.page.local.did_not_pass')}>
                <ul class="d-refuse">
                    {#each pv.refusals ?? [] as r, i (i)}
                        <li class="pp-ident"><Ident text={r.path ? t('skill.publish.report.finding_path', { code: r.code, path: r.path }) : r.code} />{#if r.detail}<small>{r.detail}</small>{/if}</li>
                    {/each}
                </ul>
            </Panel>
        {/if}
        {#if keptRows.length}
            <Panel label={t('publish.page.local.did_not_pass')}>
                <ul class="d-refuse">
                    {#each keptRows as r, i (i)}<li class="pp-ident"><Ident text={r.path ? t('skill.publish.report.finding_path', { code: r.code, path: r.path }) : r.code} /></li>{/each}
                </ul>
            </Panel>
        {/if}
        {#if notes}<Panel label={t('publish.page.local.notes')}><p class="d-lead d-lead--first">{notes}</p></Panel>{/if}
        {#if cleanRoomSkipExpected({ kind })}
            <Panel label={t('publish.page.checks.clean_room_label')}>
                <p class="d-mention" data-pp="CleanRoomMention">
                    <span class="d-mk"><Icon name="info" size={14} /></span>
                    <span><b>{t('publish.page.checks.clean_room_skipped')}</b> {t('publish.page.checks.clean_room_why')}</span>
                </p>
            </Panel>
        {/if}
        {#if pv?.files?.length}
            <Panel label={t('publish.page.local.files_read')}>
                <ul class="d-files">
                    {#each pv.files ?? [] as f (f.path)}<li><span class="d-files__p pp-ident"><Ident text={f.path} /></span>{#if f.size !== null}<span>{bytesText(f.size, t)}</span>{/if}</li>{/each}
                </ul>
            </Panel>
        {/if}
    {:else}
        <p class="d-note">{t('publish.page.local.nothing_sent')}</p>
    {/if}
</div>
