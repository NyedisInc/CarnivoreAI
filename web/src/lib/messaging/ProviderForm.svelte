
<script lang="ts">
    import Check from '../../opscenter/ui/Check.svelte';
    import { secretField } from '../secret-field';
    import type { Translate } from '../sessions/types';
    import type { ProviderBody } from './api';

    interface Props {
        t: Translate;
        busy: boolean;
        onSave: (body: ProviderBody) => void;
        onCancel: () => void;
    }
    const { t, busy, onSave, onCancel }: Props = $props();

    let name = $state('imessage');
    let baseUrl = $state('');
    let token = $state('');
    let senders = $state('');
    let ownerLabel = $state('');
    let allowPrivate = $state(false);
    let allowPlainHttp = $state(false);

    const handles = $derived(senders.split(/[\n,]/).map((s) => s.trim()).filter(Boolean));
    const ready = $derived(name.trim() !== '' && baseUrl.trim() !== '' && token.trim() !== '' && handles.length > 0);

    function body(): ProviderBody {
        const secret = token.trim();
        return {
            name: name.trim(), base_url: baseUrl.trim(), owner_senders: handles,
            ...(secret.startsWith('op://') ? { token_ref: secret } : { token: secret }),
            ...(ownerLabel.trim() ? { owner_label: ownerLabel.trim() } : {}),
            allow_private: allowPrivate, allow_plain_http: allowPrivate && allowPlainHttp,
        };
    }
</script>

<form class="tm__srv" data-messaging="provider-form" onsubmit={(e) => { e.preventDefault(); if (ready && !busy) onSave(body()); }}>
    <div class="tm__srv-head"><span class="oc-key">{t('messaging.ui.provider.add_title')}</span></div>
    <div class="tm__srv-grid">
        <label class="tm__field">
            <span class="oc-key">{t('messaging.ui.provider.name')}</span>
            <input class="oc-field" type="text" bind:value={name} disabled={busy} maxlength="40" autocomplete="off" data-messaging="name" />
        </label>
        <label class="tm__field">
            <span class="oc-key">{t('messaging.ui.provider.owner_label')}</span>
            <input class="oc-field" type="text" bind:value={ownerLabel} disabled={busy} maxlength="40" autocomplete="off"
                placeholder={t('messaging.ui.provider.owner_label_hint')} data-messaging="owner-label" />
        </label>
        <label class="tm__field">
            <span class="oc-key">{t('messaging.ui.provider.base_url')}</span>
            <input class="oc-field" use:secretField bind:value={baseUrl} disabled={busy} placeholder={t('messaging.ui.provider.secret_placeholder')}
                data-messaging="base-url" />
        </label>
        <label class="tm__field">
            <span class="oc-key">{t('messaging.ui.provider.token')}</span>
            <input class="oc-field" use:secretField bind:value={token} disabled={busy} placeholder={t('messaging.ui.provider.token_hint')}
                data-messaging="token" />
        </label>
        <label class="tm__field">
            <span class="oc-key">{t('messaging.ui.provider.owner_senders')}</span>
            <input class="oc-field" use:secretField bind:value={senders} disabled={busy} placeholder={t('messaging.ui.provider.owner_senders_hint')}
                data-messaging="owner-senders" />
        </label>
    </div>
    <Check label={t('messaging.ui.provider.allow_private')} hint={t('messaging.ui.provider.allow_private_hint')} checked={allowPrivate} disabled={busy}
        data-messaging="allow-private" onToggle={(next) => { allowPrivate = next; if (!next) allowPlainHttp = false; }} />
    <Check label={t('messaging.ui.provider.allow_plain_http')} hint={t('messaging.ui.provider.allow_plain_http_hint')} checked={allowPlainHttp}
        disabled={busy || !allowPrivate} data-messaging="allow-plain-http" onToggle={(next) => (allowPlainHttp = next)} />
    <div class="tm__actions">
        <button type="button" class="modal-btn modal-btn-secondary" disabled={busy} data-messaging="provider-cancel" onclick={onCancel}>{t('messaging.ui.cancel')}</button>
        <button type="submit" class="modal-btn modal-btn-confirm" disabled={busy || !ready} data-messaging="provider-save">{t('messaging.ui.provider.save')}</button>
    </div>
</form>
