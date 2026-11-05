
<script lang="ts">
    import { Button, Select } from '../base';
    import Check from '../../opscenter/ui/Check.svelte';
    import { t as reactiveT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import { authFetch } from '../../opscenter/api/auth.svelte';
    import { errorText } from '../settings-page/panel-kit/error-text';
    import {
        adjustBeast, autoOffChoice, BEAST_AUTO_OFF_HOURS, beastStatus, beastUntilText, disarmBeast, openBeastConfirm, startBeastStatus,
        type BeastAdjust,
    } from './control.svelte';

    interface Props {
        t?: Translate;
        fetcher?: typeof authFetch;
        onArm?: () => Promise<void>;
    }
    const { t = reactiveT, fetcher = authFetch, onArm = openBeastConfirm }: Props = $props();

    let busy = $state(false);
    let problem = $state('');
    startBeastStatus();

    const status = $derived(beastStatus.data);
    const armed = $derived(status?.enabled === true);
    const until = $derived(beastUntilText(status));
    let hours = $state(autoOffChoice(beastStatus.data));
    $effect(() => {
        hours = autoOffChoice(status);
    });
    const choices = BEAST_AUTO_OFF_HOURS.map((choice) => ({
        value: choice === null ? '' : String(choice),
        label: choice === null ? t('beast.auto_off.never') : t('beast.auto_off.hours', { count: choice }),
    }));

    async function run(action: () => Promise<void>): Promise<void> {
        if (busy) return;
        busy = true;
        problem = '';
        try {
            await action();
        } catch (error) {
            problem = errorText(error);
        } finally {
            busy = false;
        }
    }

    const change = (change: BeastAdjust): Promise<void> => run(() => adjustBeast(change, fetcher));
</script>

<section class="beast-strip" data-beast-strip={armed ? 'on' : 'off'} aria-label={t('beast.strip.label')}>
    <div class="beast-strip__head">
        <span class="pl-label">{t('beast.strip.label')}</span>
        {#if armed}
            <span class="beast-strip__state beast-strip__state--on" data-beast-strip-state>
                {until ? t('beast.strip.on_until', { time: until }) : t('beast.strip.on_open')}
            </span>
            <Button variant="danger" data-beast-strip-disarm disabled={busy} onclick={() => void run(disarmBeast)}>{t('beast.strip.disarm')}</Button>
        {:else}
            <span class="beast-strip__state" data-beast-strip-state>{t('beast.strip.off')}</span>
            <Button variant="danger" data-beast-strip-arm disabled={busy} onclick={() => void run(onArm)}>{t('beast.strip.arm')}</Button>
        {/if}
    </div>
    {#if armed}
        <div class="beast-strip__live">
            <Check role="switch" label={t('beast.prompts.label')} hint={t('beast.prompts.hint')} checked={status?.prompts === true}
                disabled={busy} onToggle={(next) => void change({ prompts: next })} data-beast-strip-prompts="" />
            <label class="beast-strip__off">
                <span class="pl-label">{t('beast.auto_off.label')}</span>
                <Select bind:value={hours} options={choices} disabled={busy} data-beast-strip-auto-off aria-label={t('beast.auto_off.label')}
                    onchange={() => void change({ hours: hours === '' ? null : Number(hours) })} />
            </label>
        </div>
    {/if}
    {#if problem}<p class="beast-strip__problem" role="alert">{problem}</p>{/if}
</section>

<style>
    @layer components {
        .beast-strip { display: flex; flex-direction: column; gap: var(--oc-space-3); padding-bottom: var(--oc-space-3); box-shadow: 0 1px 0 var(--oc-line-rule); }
        .beast-strip__head { display: flex; flex-wrap: wrap; align-items: center; gap: var(--oc-space-3); }
        .beast-strip__state { font-family: var(--font-mono); font-size: var(--oc-fs-body); color: var(--oc-text-dim); flex: 1 1 auto; min-width: 0; }
        .beast-strip__state--on { color: var(--oc-green); }
        .beast-strip__live { display: flex; flex-direction: column; gap: var(--oc-space-2); }
        .beast-strip__off { display: flex; align-items: center; gap: var(--oc-space-2); }
        .beast-strip__problem { margin: 0; color: var(--oc-coral); font-family: var(--font-mono); font-size: var(--oc-fs-body); }
    }
</style>
