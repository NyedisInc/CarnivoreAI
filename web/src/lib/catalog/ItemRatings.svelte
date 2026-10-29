
<script lang="ts">
    import { SKILL_KEYS } from '../../../../client/js/labels/skill.js';
    import RatingControl from './RatingControl.svelte';
    import RatingHistogram from './RatingHistogram.svelte';
    import RegisterGate from './RegisterGate.svelte';
    import { createRegisterGate } from './register-gate.svelte';
    import { browserPublishHost, type PublishHost } from './publish';
    import type { CatalogHost } from './catalog';
    import RatingStars from '../rating/RatingStars.svelte';
    import type { RatingsReader } from './ratings-reader.svelte';
    import { RATINGS_SECTION_ID } from './item-feedback';
    import type { Translate } from '../sessions/types';

    interface Props {
        itemId: string;
        host: CatalogHost;
        t: Translate;
        signedIn: boolean;
        guest?: boolean;
        installed?: boolean;
        myLogin: string | null;
        reader: RatingsReader;
        publishHost?: PublishHost;
    }

    const { itemId, host, t, signedIn, guest = false, installed = true, myLogin, reader, publishHost = browserPublishHost() }: Props = $props();

    const gate = createRegisterGate(() => publishHost, t('community.gate.failed'), 'rate');

    const mine = $derived(
        signedIn && myLogin ? (reader.view.texts.find((r) => r.login === myLogin) ?? null) : null,
    );
    const view = $derived(reader.view);
</script>

<section class="trt" id={RATINGS_SECTION_ID} aria-label={t('themes.page.ratings.heading')}>
    <h3 class="trt__label">{t('themes.page.ratings.heading')}</h3>
    {#if reader.loading && view.shape === 'unavailable'}
        <p class="trt__note">{t(SKILL_KEYS.ratingLoading)}</p>
    {:else if reader.failure}
        <p class="trt__note trt__note--out" role="status">{t(SKILL_KEYS.ratingUnavailable, { reason: reader.failure })}</p>
    {:else if view.shape === 'none'}
        <p class="trt__note">{t(SKILL_KEYS.ratingNone)}</p>
    {:else if view.shape === 'rated'}
        <div class="trt__score">
            <RatingStars value={view.average ?? 0} size={16} label={t(SKILL_KEYS.ratingAverage, { average: view.average ?? 0 })} />
            <span class="trt__count">{t(SKILL_KEYS.ratingCount, { count: view.count })}</span>
        </div>
        <RatingHistogram rows={view.histogram} {t} />
    {/if}
    <RatingControl
        {itemId}
        {host}
        {t}
        signedIn={signedIn || guest}
        {installed}
        gate={signedIn ? gate : undefined}
        initialStars={mine?.stars ?? null}
        initialText={mine?.text ?? null}
        onWritten={() => reader.reload()}
    />
    <RegisterGate {gate} host={publishHost} {t} />
</section>

<style>
  @layer components {
    .trt {
        display: flex;
        flex-direction: column;
        gap: 8px;
        padding-top: 10px;
        border-top: 1px solid var(--oc-line-faint);
        scroll-margin-top: 8px;
    }

    .trt__label {
        margin: 0;
        font-size: var(--oc-fs-micro, 10px);
        font-weight: 600;
        letter-spacing: var(--oc-tracking-label, 0.08em);
        text-transform: uppercase;
        color: var(--oc-text-dim);
    }

    .trt__score {
        display: flex;
        align-items: center;
        gap: 10px;
    }

    .trt__count,
    .trt__note {
        margin: 0;
        font-size: var(--oc-fs-label, 12px);
        color: var(--oc-text-secondary);
    }

    .trt__note--out {
        padding: 6px 8px;
        border-left: 2px solid var(--oc-yellow);
        background: var(--cat-raised);
        color: var(--oc-text-primary);
    }
  }
</style>
