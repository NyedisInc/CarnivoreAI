
<script lang="ts">
    import { t as reactiveT, type Translate } from '../sdk';
    import { Button } from '../sdk/ui';
    import { fetchLocation, saveLocation, type Fetcher, type LocationView, type LocationWarning } from './location-api';
    import { errorText } from './settings-api';

    interface Props {
        t?: Translate;
        fetcher?: Fetcher;
    }
    const { t = reactiveT, fetcher }: Props = $props();

    let view = $state<LocationView | null>(null);
    let draft = $state('');
    let busy = $state(false);
    let note = $state('');
    let problem = $state('');
    let advice = $state<readonly LocationWarning[]>([]);

    const changed = $derived(view !== null && draft.trim() !== view.location);
    const warnings = $derived([...new Map([...(view?.warnings ?? []), ...advice].map((w) => [`${w.code}|${w.field ?? ''}`, w])).values()]);

    async function load(): Promise<void> {
        try {
            view = await fetchLocation(fetcher);
            draft = view.location;
            problem = '';
        } catch (error) {
            problem = errorText(error);
        }
    }
    void load();

    async function write(value: string): Promise<void> {
        busy = true;
        problem = '';
        note = '';
        advice = [];
        try {
            advice = (await saveLocation(value, fetcher)).warnings;
            note = t('cplug.save.location.saved');
            await load();
        } catch (error) {
            problem = errorText(error);
        } finally {
            busy = false;
        }
    }
</script>

<div class="tm" data-tm="location">
    <label class="tm__field">
        <span class="oc-key">{t('cplug.save.settings.location_label')}</span>
        <input
            class="oc-field"
            type="text"
            spellcheck="false"
            autocomplete="off"
            placeholder={t('cplug.save.location.placeholder')}
            bind:value={draft}
            disabled={busy || view === null}
            data-tm="location-field"
        />
    </label>
    <p class="tm__sub">{t('cplug.save.settings.location_hint')}</p>
    {#if view}
        <p class="tm__sub" data-tm="location-root">{t('cplug.save.location.now', { root: view.root })}</p>
        {#if view.available}
            <p class="tm__sub" data-tm="location-ok">{t('cplug.save.location.ok')}</p>
        {:else}
            <p class="tm__problem" role="alert" data-tm="location-unavailable">{t('cplug.save.location.unavailable', { reason: view.error })}</p>
        {/if}
        {#each view.refusals as refusal (refusal)}
            <p class="tm__problem" data-tm="location-refusal">{refusal}</p>
        {/each}
        {#if warnings.length}
            <div class="tm__warn" data-tm="location-warn">
                {#each warnings as warning (`${warning.code}|${warning.field ?? ''}`)}
                    <p data-tm="location-warn-message">{warning.message}</p>
                    {#if warning.detail}<p class="tm__sub" data-tm="location-warn-detail">{warning.detail}</p>{/if}
                {/each}
            </div>
        {/if}
    {/if}
    <div class="tm__actions">
        <Button data-tm="location-default" disabled={busy || !view || view.location === ''} onclick={() => void write('')}>
            {t('cplug.save.location.use_default')}
        </Button>
        <Button variant="confirm" data-tm="location-save" disabled={busy || !changed} onclick={() => void write(draft)}>
            {t('cplug.save.location.save')}
        </Button>
    </div>
    {#if note}<p class="tm__note" role="status" data-tm="location-note">{note}</p>{/if}
    {#if problem}<p class="tm__problem" role="alert" data-tm="location-problem">{problem}</p>{/if}
</div>
