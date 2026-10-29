
<script lang="ts">
    import { untrack } from 'svelte';
    import Button from '../base/Button.svelte';
    import AppealForm from './AppealForm.svelte';
    import './detail.css';
    import './panel.css';
    import FixList from './FixList.svelte';
    import { defaultVersion, factsUnknown, maxVersion, selectedRecord, sentRows, stepFor, versionRows } from './item-model';
    import { isWizard, stageWordOf, stepperIndex, waitLeadKey } from './next-step-model';
    import { reduced } from './motion';
    import type { PageProps } from './props';
    import SendWizard from './SendWizard.svelte';
    import Stepper from './Stepper.svelte';
    import { draftsOf } from './wizard-state.svelte';
    import WithdrawConfirm from './WithdrawConfirm.svelte';

    const { store, actions, t }: PageProps = $props();

    const FADE_MS = 260;

    const rec = $derived(selectedRecord(store));
    const facts = $derived(rec ? store.facts[rec.location] : undefined);
    const step = $derived(rec && !factsUnknown(store, rec) ? stepFor(store, rec) : null);
    const sentVersions = $derived(rec ? versionRows(rec, store.mine).map((r) => r.version) : []);
    const refusedVersion = $derived(rec && step?.kind === 'fix' && step.local ? (store.checkOf(rec.location)?.version ?? '') : '');
    const start = $derived(refusedVersion || defaultVersion(facts?.declared_version ?? '', maxVersion(rec ? sentRows(store, rec).map((r) => r.version) : [])));
    const drafts = $derived(draftsOf(store));
    const busy = $derived(rec ? drafts.of(rec.location).phase !== 'idle' : false);
    const label = $derived(step && isWizard(step) && !busy ? t('publish.page.next.label_send') : t('publish.page.next.label'));

    let body = $state<HTMLElement | null>(null);
    let seen: { location: string; key: string } | null = null;
    $effect(() => {
        const location = rec?.location ?? '';
        const key = step ? `${step.kind}:${'state' in step ? step.state : 'why' in step ? step.why : ''}` : '';
        untrack(() => {
            const slot = body?.closest('.d-slot') as HTMLElement | null;
            if (seen && seen.location === location && seen.key !== key && !reduced() && slot?.animate) {
                slot.animate([{ opacity: 0.3 }, { opacity: 1 }], { duration: FADE_MS, easing: 'ease-out' });
            }
            seen = { location, key };
        });
    });
</script>

<div data-pp="NextStep" bind:this={body}>
    {#if rec && step}
        <div class="d-slot__in">
            <header class="d-panel__bar d-panel__bar--primary"><h3 class="pl-label d-panel__lab d-slot__lab">{label}</h3></header>
            <div class="d-panel__body">
            {#if step.kind === 'wait'}
                <Stepper current={(stepperIndex(step) ?? 0) as 0 | 1 | 2 | 3} {t} />
                <p class="d-slot__state" role="status">{t(waitLeadKey(step.state))}</p>
                <p class="d-slot__why">{t('publish.page.next.wait.why', { name: rec.name, version: step.sub.version, stage: stageWordOf(step.sub, t) })}</p>
                {#if step.withdraw}<WithdrawConfirm {store} {actions} {t} sub={step.sub} location={rec.location} />{/if}
            {:else if step.kind === 'fix'}
                <FixList {store} {actions} {t} {rec} {step} {start} sent={sentVersions} />
            {:else if step.kind === 'appeal'}
                <AppealForm {store} {actions} {t} sub={step.sub} left={step.left} location={rec.location} onNew={() => store.forceNew(rec.location, rec.latest?.id ?? '')} />
            {:else if step.kind === 'live'}
                <p class="d-slot__state">{t('publish.page.next.live.lead', { version: step.sub.version })}</p>
                <p class="d-slot__why">{t('publish.page.next.live.why')}</p>
                <div class="pp-foot"><Button onclick={() => store.forceNew(rec.location, rec.latest?.id ?? '')}>{t('publish.page.next.button.check_new')}</Button></div>
            {:else}
                <SendWizard {store} {actions} {t} step={step.kind === 'check' ? step : null} />
            {/if}
            </div>
        </div>
    {/if}
</div>
