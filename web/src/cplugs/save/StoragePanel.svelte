
<script lang="ts">
    import { t as reactiveT, scaleStep, type Translate } from '../sdk';
    import { Button, LimitGauge } from '../sdk/ui';
    import FolderUnits from './FolderUnits.svelte';
    import {
        CAP_MIN_GB,
        dropsPoints,
        errorText,
        fetchSaveSettings,
        fetchUsage,
        gbText,
        saveCap,
        sliderMax,
        sliderValue,
        type Fetcher,
        type SaveSettings,
        type Usage,
    } from './settings-api';

    interface Props {
        t?: Translate;
        fetcher?: Fetcher;
    }
    const { t = reactiveT, fetcher }: Props = $props();

    let usage = $state<Usage | null>(null);
    let settings = $state<SaveSettings | null>(null);
    let value = $state(CAP_MIN_GB);
    let pending = $state<number | null>(null);
    let busy = $state(false);
    let note = $state('');
    let problem = $state('');

    const percent = $derived(usage && usage.cap_bytes > 0 ? (usage.history_bytes / usage.cap_bytes) * 100 : 0);
    const meterText = $derived(
        usage ? t('cplug.save.settings.meter', { used: gbText(usage.history_bytes), cap: gbText(usage.cap_bytes) }) : '',
    );
    const locked = $derived(settings?.cap_env_locked ?? false);

    async function load(): Promise<void> {
        try {
            const [u, s] = await Promise.all([fetchUsage(fetcher), fetchSaveSettings(fetcher)]);
            usage = u;
            settings = s;
            value = sliderValue(s.cap_gb);
            problem = '';
        } catch (error) {
            problem = errorText(error);
        }
    }
    void load();

    async function write(capGb: number): Promise<void> {
        busy = true;
        problem = '';
        note = '';
        try {
            usage = await saveCap(capGb, fetcher);
            value = capGb;
            pending = null;
            note = t('cplug.save.settings.saved', { cap: `${capGb} gb` });
        } catch (error) {
            problem = errorText(error);
            value = sliderValue(settings?.cap_gb ?? capGb);
            pending = null;
        } finally {
            busy = false;
        }
    }

    function onRelease(): void {
        note = '';
        if (!usage || value === sliderValue(settings?.cap_gb ?? value)) return;
        if (dropsPoints(value, usage.history_bytes)) {
            pending = value;
            return;
        }
        void write(value);
    }

    function cancel(): void {
        pending = null;
        value = sliderValue(settings?.cap_gb ?? value);
    }
</script>

<div class="tm" data-tm="storage">
    {#if usage}
        <div class="tm__meter">
            <LimitGauge variant="fill" pct={percent} scale={scaleStep(percent)} {meterText} height={8} />
            <p class="tm__figs" data-tm="figures">
                {t('cplug.save.settings.meter', { used: gbText(usage.history_bytes), cap: gbText(usage.cap_bytes) })}
            </p>
            <p class="tm__sub" data-tm="counts">
                {t('cplug.save.settings.counts', {
                    points: usage.points,
                    conversations: usage.conversations,
                    pinned: usage.pinned,
                })}
            </p>
        </div>
        <label class="tm__slider">
            <span class="oc-key">{t('cplug.save.settings.cap_label')}</span>
            <input
                class="tm__range"
                type="range"
                min={CAP_MIN_GB}
                max={sliderMax(settings?.cap_gb ?? value)}
                step="1"
                bind:value
                disabled={locked || busy}
                aria-label={t('cplug.save.settings.cap_label')}
                data-tm="cap"
                onchange={onRelease}
            />
            <span class="tm__value" data-tm="cap-value">{value} gb</span>
        </label>
        {#if locked && settings}
            <p class="tm__sub" data-tm="locked">{t('cplug.save.settings.env_locked', { name: settings.cap_env_var })}</p>
        {/if}
        {#if pending !== null}
            <div class="tm__warn" role="alert" data-tm="warn">
                <p>{t('cplug.save.settings.lower_warning', { cap: `${pending} gb`, used: gbText(usage.history_bytes) })}</p>
                <div class="tm__actions">
                    <Button data-tm="cancel" disabled={busy} onclick={cancel}>
                        {t('cplug.save.settings.cancel')}
                    </Button>
                    <Button variant="confirm" data-tm="confirm" disabled={busy} onclick={() => void write(pending!)}>
                        {t('cplug.save.settings.confirm')}
                    </Button>
                </div>
            </div>
        {/if}
    {:else if !problem}
        <p class="tm__sub">{t('cplug.save.settings.loading')}</p>
    {/if}
    {#if note}<p class="tm__note" role="status" data-tm="note">{note}</p>{/if}
    {#if problem}<p class="tm__problem" role="alert" data-tm="problem">{problem}</p>{/if}
    <FolderUnits {t} {fetcher} />
</div>
