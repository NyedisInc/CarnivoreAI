
<script lang="ts">
    import { t as reactiveT, type Translate } from '../sdk';
    import {
        CAPTURE_SCOPES,
        errorText,
        fetchCaptureScope,
        saveCaptureScope,
        type CaptureScope,
        type Fetcher,
    } from './settings-api';

    interface Props {
        t?: Translate;
        fetcher?: Fetcher;
    }
    const { t = reactiveT, fetcher }: Props = $props();

    let current = $state<CaptureScope | null>(null);
    let busy = $state(false);
    let note = $state('');
    let problem = $state('');

    async function load(): Promise<void> {
        try {
            current = (await fetchCaptureScope(fetcher)).capture_scope;
            problem = '';
        } catch (error) {
            problem = errorText(error);
        }
    }
    void load();

    async function choose(value: CaptureScope): Promise<void> {
        if (value === current) return;
        busy = true;
        problem = '';
        note = '';
        try {
            current = (await saveCaptureScope(value, fetcher)).capture_scope;
            note = t('cplug.save.settings.saved_short');
        } catch (error) {
            problem = errorText(error);
        } finally {
            busy = false;
        }
    }

    function keyOf(value: CaptureScope): string {
        return value.replace('+', '_');
    }
</script>

<div class="tm" data-tm="scope">
    {#if current}
        <div class="tm__choices" role="radiogroup" aria-label={t('cplug.save.settings.scope_label')}>
            {#each CAPTURE_SCOPES as value (value)}
                <button
                    type="button"
                    role="radio"
                    class="oc-choice"
                    aria-checked={current === value}
                    data-tm-scope={value}
                    disabled={busy}
                    onclick={() => void choose(value)}
                >
                    <span class="oc-choice__top">
                        <span class="oc-radio"></span>
                        <span class="oc-choice__name">{t(`cplug.save.settings.scope.${keyOf(value)}`)}</span>
                        {#if current === value}
                            <span class="oc-choice__use">{t('cplug.save.settings.in_use')}</span>
                        {/if}
                    </span>
                    <span class="oc-choice__desc">{t(`cplug.save.settings.scope.${keyOf(value)}.desc`)}</span>
                </button>
            {/each}
        </div>
    {:else if !problem}
        <p class="tm__sub">{t('cplug.save.settings.loading')}</p>
    {/if}
    {#if note}<p class="tm__note" role="status" data-tm="note">{note}</p>{/if}
    {#if problem}<p class="tm__problem" role="alert" data-tm="problem">{problem}</p>{/if}
</div>
