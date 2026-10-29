
<script lang="ts">
    import type { Translate } from '../sessions/types';

    interface Props {
        name: string;
        dependents: readonly string[];
        busy?: boolean;
        onConfirm: () => void;
        onCancel: () => void;
        t: Translate;
    }

    const { name, dependents, busy = false, onConfirm, onCancel, t }: Props = $props();
</script>

<div class="plp__confirm" data-cplug-disable-ask role="group" aria-label={t('plugins.page.disable.title', { name })}>
    <p class="plp__confirm-text" data-cplug-dependents>
        <strong>{t('plugins.page.disable.title', { name })}</strong>
        {t('plugins.page.disable.body', { name, dependents: dependents.join(', ') })}
    </p>
    <div class="plp-actions">
        <button type="button" class="modal-btn modal-btn-secondary" data-cplug-disable-cancel disabled={busy} onclick={onCancel}>{t('plugins.page.disable.cancel')}</button>
        <button type="button" class="modal-btn modal-btn-danger" data-cplug-disable-confirm disabled={busy} onclick={onConfirm}>{t('plugins.page.disable.confirm')}</button>
    </div>
</div>
