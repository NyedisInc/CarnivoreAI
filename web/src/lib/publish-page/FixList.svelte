
<script lang="ts">
    import Button from '../base/Button.svelte';
    import { buttonAttrs } from '../base/classes';
    import Field from '../base/Field.svelte';
    import type { Translate } from '../sessions/types';
    import type { PageActions } from './actions';
    import Ident from './Ident.svelte';
    import CheckMark from './CheckMark.svelte';
    import { storedCodes } from './checks-model';
    import type { ItemRecord } from './list-model';
    import type { Step } from './next-step-model';
    import type { PageStore } from './page-store.svelte';
    import { findingSentence, gateLabelKey, gatesById, GATE_IDS, resultOf } from './report-format';
    import './checks.css';

    interface Props {
        store: PageStore;
        actions: PageActions;
        t: Translate;
        rec: ItemRecord;
        step: Extract<Step, { kind: 'fix' }>;
        start: string;
        sent: readonly string[];
    }
    const { store, actions, t, rec, step, start, sent }: Props = $props();

    const VERSION = /^\d+\.\d+\.\d+$/;
    let typed = $state<string | null>(null);
    let busy = $state(false);
    let bad = $state(false);
    const version = $derived(typed ?? start);
    const raise = $derived(sent.includes(version));

    const sub = $derived(step.sub);
    /* could not be read */
    const unread = $derived(!step.local && !!sub && !store.reports[sub.id] && !!store.failure.report);
    const report = $derived(!step.local && sub ? store.reports[sub.id] : undefined);
    $effect(() => {
        if (!step.local && sub && !store.reports[sub.id] && !store.failure.report) void store.loadReport(sub.id);
    });

    const failed = $derived.by(() => {
        if (!report) return [];
        const by = gatesById(report.gates);
        return GATE_IDS.filter((id) => resultOf(by.get(id)) === 'did_not_pass').map((id) => ({ id, finding: by.get(id)?.findings[0] }));
    });
    const refusals = $derived(
        (store.checkOf(rec.location)?.preview?.refusals ?? []).map((r) =>
            r.path ? t('skill.publish.report.finding_path', { code: r.code, path: r.path }) : r.code,
        ),
    );
    const stored = $derived.by(() => {
        const entry = store.checkOf(rec.location);
        if (!entry || entry.preview) return [];
        const found = entry.findings ?? [];
        const lines = found.map((f) => t('skill.publish.report.finding_path', { code: f.code, path: f.path }));
        return [...new Set([...lines, ...storedCodes(entry.summary).filter((code) => !found.some((f) => f.code === code))])];
    });

    async function check(): Promise<void> {
        if (busy) return;
        bad = !VERSION.test(version);
        if (bad) return;
        busy = true;
        await actions.check(rec.location, version);
        busy = false;
    }
</script>

<div class="pp-fix" data-pp="FixList">
    {#if !unread}<p class="d-slot__why">{t(raise ? 'publish.page.next.fix.lead_raise' : 'publish.page.next.fix.lead')}</p>{/if}
    {#if step.local}
        <ul class="d-fixlist">
            {#each refusals as line (line)}
                <li><CheckMark result="did_not_pass" shapeOnly {t} /><span class="pp-ident"><Ident text={line} /></span></li>
            {/each}
            {#if refusals.length === 0}{#each stored as code (code)}<li><CheckMark result="did_not_pass" shapeOnly {t} /><span class="pp-ident"><Ident text={code} /></span></li>{/each}{/if}
        </ul>
    {:else}
        {#if store.failure.report}<p class="d-reason" data-tone="yellow" role="alert">{store.failure.report}</p>{/if}
        {#if unread}<div class="pp-foot"><Button size="sm" onclick={() => sub && void store.loadReport(sub.id)}>{t('skill.action.retry')}</Button></div>{/if}
        <ul class="d-fixlist">
            {#each failed as gate (gate.id)}
                <li>
                    <CheckMark result="did_not_pass" shapeOnly {t} />
                    <button type="button" class="d-link" {...buttonAttrs('quiet', 'md')} onclick={() => sub && store.openEvent(`${sub.id}:gates`)}>{t(gateLabelKey(gate.id))}</button>
                    {#if gate.finding}<span class="d-fixlist__f pp-ident"><Ident text={findingSentence(gate.finding, t)} /></span>{/if}
                </li>
            {/each}
        </ul>
    {/if}
    <div class="d-act">
        <label class="d-field">{t('skill.publish.version')}<Field value={version} oninput={(e) => { typed = e.currentTarget.value.trim(); bad = false; }} aria-label={t('skill.publish.version')} autocomplete="off" spellcheck={false} /></label>
        <Button variant="confirm" id="d-check" disabled={busy} onclick={() => void check()}>{t('publish.page.next.button.fixed')}</Button>
        {#if bad}<span class="d-reason" data-tone="yellow" role="alert">{t('publish.page.next.version_format')}</span>
        {:else if store.failure.check}<span class="d-reason" data-tone="yellow" role="alert">{store.failure.check}</span>{/if}
    </div>
</div>
