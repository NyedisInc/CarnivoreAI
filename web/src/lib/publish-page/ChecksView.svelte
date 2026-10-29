
<script lang="ts">
    import { untrack } from 'svelte';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import Button from '../base/Button.svelte';
    import Ident from './Ident.svelte';
    import CheckRail from './CheckRail.svelte';
    import CheckRow from './CheckRow.svelte';
    import { buildCells, defaultOpen, fillPlan, mentionSkipped, phaseOf, summaryOf } from './checks-model';
    import { reduced } from './motion';
    import Panel from './Panel.svelte';
    import type { PageProps } from './props';
    import { GATE_IDS, type GateId } from './report-format';
    import './checks.css';

    const { store, t }: PageProps = $props();

    const sid = $derived(store.mid && store.mid.ev.endsWith(':gates') ? store.mid.ev.slice(0, -':gates'.length) : '');
    const sub = $derived(store.mine?.find((row) => row.id === sid) ?? null);
    const report = $derived(store.reports[sid] ?? null);
    const hasReport = $derived(report !== null);
    const phase = $derived(phaseOf(sub?.gate_state, report !== null));
    let shown = $state<number>(GATE_IDS.length);
    const cells = $derived(buildCells(report, phase === 'running', shown));
    /* could not be read */
    const unread = $derived(phase === 'done' && !report && !!store.failure.report);
    const summary = $derived(unread ? null : summaryOf(cells, phase));
    const summaryText = $derived(summary ? t(summary.key, summary.params) : '');
    const mention = $derived(mentionSkipped(report, sub?.kind));
    const title = $derived(sub ? `${sub.name.split('/').pop() ?? sub.name} ${sub.version}` : '');

    let toggled = $state<Record<string, boolean>>({});
    let more = $state<Record<string, boolean>>({});
    let host = $state<HTMLElement | null>(null);

    const isOpen = (id: GateId): boolean => toggled[id] ?? defaultOpen(cells.find((c) => c.id === id)?.result ?? 'not_run');

    $effect.pre(() => {
        if (!hasReport) return;
        const id = sid;
        const plan = untrack(() => {
            const observed = store.railFill[id] === true;
            if (observed) store.railFill[id] = false;
            return fillPlan({ observed, reducedMotion: reduced() });
        });
        if (plan.steps.length === 1) {
            shown = plan.steps[0] ?? GATE_IDS.length;
            return;
        }
        let at = 0;
        let timer: ReturnType<typeof setTimeout> | undefined;
        const step = (): void => {
            shown = plan.steps[at++] ?? GATE_IDS.length;
            if (at < plan.steps.length) timer = setTimeout(step, plan.intervalMs);
        };
        shown = 0;
        timer = setTimeout(step, plan.intervalMs);
        return () => {
            clearTimeout(timer);
            shown = GATE_IDS.length;
        };
    });

    function tick(id: GateId): void {
        toggled[id] = !isOpen(id);
        queueMicrotask(() => host?.querySelector<HTMLElement>(`[data-gate="${id}"] .d-chk__h`)?.focus({ preventScroll: true }));
    }
</script>

<div class="d-checks" data-pp="ChecksView" data-sub={sid} bind:this={host}>
    <h2 class="d-name">{t('publish.page.checks.title')}</h2>
    <p class="d-kind">
        {#if title}<span class="pp-ident"><Ident text={title} /></span>{/if}
        {#if summaryText}<span>{summaryText}</span>{/if}
    </p>
    {#if unread}
        <Panel label={t('publish.page.checks.title')}>
            <div class="pp-ck__unread" role="alert">
                <p class="pp-ck__fail">{store.failure.report}</p>
                <Button size="sm" onclick={() => void store.loadReport(sid)}>{t('skill.action.retry')}</Button>
            </div>
        </Panel>
    {:else}
        {#if phase === 'done' && !report}<p class="d-note">{t('skill.publish.report.loading')}</p>{/if}
        <Panel label={t('publish.page.checks.glance')} aux={summaryText}>
            <p class="d-lead d-lead--first">{t('publish.page.checks.glance_lead')}</p>
            <CheckRail {cells} open={isOpen} {t} onToggle={tick} />
        </Panel>
        <Panel label={t('publish.page.checks.by_check')} aux={t('publish.page.checks.by_check_aux')}>
            <ul class="d-chk">
                {#each cells as cell (cell.id)}
                    <CheckRow {cell} {t} expanded={isOpen(cell.id)} all={more[cell.id] === true} onToggle={() => (toggled[cell.id] = !isOpen(cell.id))} onMore={() => (more[cell.id] = true)} />
                {/each}
            </ul>
        </Panel>
    {/if}
    {#if mention}
        <Panel label={t('publish.page.checks.clean_room_label')}>
            <p class="d-mention" data-pp="CleanRoomMention">
                <span class="d-mk"><Icon name="info" size={14} /></span>
                <span><b>{t('publish.page.checks.clean_room_skipped')}</b> {t('publish.page.checks.clean_room_why')}</span>
            </p>
        </Panel>
    {/if}
</div>
