
<script lang="ts">
    import type { Translate } from '../sessions/types';
    import Button from '../base/Button.svelte';
    import { settingsDoc } from './settings-doc.svelte';

    interface Props {
        t: Translate;
    }

    const { t }: Props = $props();

    const count = $derived(settingsDoc.dirtyIds.length);
    const blocked = $derived(settingsDoc.invalidIds.length > 0);
</script>

<div class="st-footer" role="region" aria-label={t('settings.save.region')}>
    <span class="st-footer__text" role="status" aria-live="polite">
        {#if settingsDoc.saveError}
            <span class="st-footer__error" role="alert">{t('settings.save.failed', { reason: settingsDoc.saveError })}</span>
        {:else if blocked}
            <span class="st-footer__error">{t('settings.save.blocked')}</span>
        {:else if count > 0}
            {t('settings.save.pending', { count })}
        {/if}
    </span>
    <Button data-settings-discard disabled={count === 0 || settingsDoc.saving} onclick={() => settingsDoc.discard()}>
        {t('settings.save.discard')}
    </Button>
    <Button
        variant="confirm"
        data-settings-save
        disabled={count === 0 || settingsDoc.saving || blocked}
        onclick={() => void settingsDoc.save()}
    >
        {settingsDoc.saving ? t('settings.save.saving') : t('settings.save.save')}
    </Button>
</div>
