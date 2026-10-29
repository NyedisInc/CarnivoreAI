
<script lang="ts">
    import { t as reactiveT } from '../../i18n/index.svelte';
    import type { Translate } from '../../sessions/types';
    import { Button, Field, Select } from '../../base';
    import Check from '../../../opscenter/ui/Check.svelte';
    import '../../settings-page/panel-kit/panel-kit.css';
    import './destinations.css';
    import { secretField } from '../../secret-field';
    import type { Destination, Kind, KindField } from './api';
    import ModelPicker from '../../byoai/ModelPicker.svelte';
    import { complete, initialDraft, kindItems, kindOf, type Draft } from './form-logic';

    interface Props {
        t?: Translate;
        kinds: readonly Kind[];
        destination: Destination | null;
        busy?: boolean;
        onSave: (draft: Draft, scope: 'global' | 'local') => void;
        onCancel: () => void;
    }
    const { t = reactiveT, kinds, destination, busy = false, onSave, onCancel }: Props = $props();

    // svelte-ignore state_referenced_locally
    const first = kindOf(kinds, destination?.kind ?? '') ?? kinds[0]!;
    // svelte-ignore state_referenced_locally
    let draft = $state<Draft>(initialDraft(first, destination));
    let localOnly = $state(false);

    const kind = $derived(kindOf(kinds, draft.kind) ?? first);
    const editing = $derived(destination !== null);
    const ready = $derived(complete(kind, draft, destination));

    function pickKind(id: string): void {
        const next = kindOf(kinds, id);
        if (!next) return;
        draft = { ...initialDraft(next, null), name: draft.name, enabled: draft.enabled };
    }

    const label = (f: KindField): string => t(`settings.notify.field.${f.name}`);
    const isSet = (name: string): boolean => destination?.secrets[name]?.set === true;
</script>

<form class="tm__srv" data-notify="form" onsubmit={(e) => { e.preventDefault(); if (ready && !busy) onSave(draft, localOnly ? 'local' : 'global'); }}>
    <div class="tm__srv-head"><span class="oc-key">{t(editing ? 'settings.notify.dest.form.edit' : 'settings.notify.dest.form.add')}</span></div>
    <div class="nd-grid">
        {#if !editing}
            <div class="tm__field">
                <span class="oc-key">{t('settings.notify.dest.form.kind')}</span>
                <ModelPicker {t} items={kindItems(kinds, t)} value={draft.kind} onChange={pickKind} label={t('settings.notify.dest.form.kind')} grouped alpha={false}
                    disabled={busy} dataAi="kind" />
            </div>
        {/if}
        <label class="tm__field">
            <span class="oc-key">{t('settings.notify.dest.form.name')}</span>
            <Field bind:value={draft.name} disabled={busy} maxlength={80} autocomplete="off" data-notify="name" />
        </label>
        {#each kind.public_fields as field (field.name)}
            <label class="tm__field">
                <span class="oc-key">{label(field)}{field.required ? '' : ` (${t('settings.notify.dest.form.optional')})`}</span>
                {#if field.type === 'enum' && field.choices.length > 0}
                    <Select bind:value={() => draft.config[field.name] ?? '', (v) => (draft.config[field.name] = v)} disabled={busy} data-notify={`field-${field.name}`}
                        options={[...(field.required ? [] : [{ value: '', label: t('settings.notify.dest.form.default_choice') }]), ...field.choices.map((choice) => ({ value: choice, label: choice }))]} />
                {:else}
                    <Field type={field.type === 'int' ? 'number' : 'text'} bind:value={() => draft.config[field.name] ?? '', (v) => (draft.config[field.name] = v)} disabled={busy} autocomplete="off"
                        spellcheck={false} data-notify={`field-${field.name}`} />
                {/if}
            </label>
        {/each}
        {#each kind.secret_fields as field (field.name)}
            <label class="tm__field">
                <span class="oc-key">{label(field)}{field.required ? '' : ` (${t('settings.notify.dest.form.optional')})`}</span>
                <Field {@attach (node) => secretField(node as HTMLInputElement)} bind:value={() => draft.secrets[field.name] ?? '', (v) => (draft.secrets[field.name] = v)} disabled={busy}
                    placeholder={t(editing && isSet(field.name) ? 'settings.notify.dest.form.secret_keep' : field.type === 'list' ? 'settings.notify.dest.form.list_hint' : 'settings.notify.dest.form.secret_placeholder')}
                    data-notify={`secret-${field.name}`} />
                {#if editing}
                    <span class="tm__sub" data-notify={`secret-state-${field.name}`}>{t(isSet(field.name) ? 'settings.notify.dest.secret_set' : 'settings.notify.dest.secret_unset')}</span>
                {/if}
            </label>
        {/each}
    </div>
    {#if kind.allow_private}
        <Check label={t('settings.notify.dest.form.allow_private')} hint={t('settings.notify.dest.form.allow_private_hint')} checked={draft.allowPrivate} disabled={busy}
            data-notify="allow-private" onToggle={(next) => { draft.allowPrivate = next; if (!next) draft.allowPlainHttp = false; }} />
        <Check label={t('settings.notify.dest.form.allow_plain_http')} hint={t('settings.notify.dest.form.allow_plain_http_hint')} checked={draft.allowPlainHttp}
            disabled={busy || !draft.allowPrivate} data-notify="allow-plain-http" onToggle={(next) => (draft.allowPlainHttp = next)} />
    {/if}
    {#if kind.id === 'webhook' && !editing}<p class="tm__sub" data-notify="signing-note">{t('settings.notify.dest.form.signing_note')}</p>{/if}
    <Check role="switch" label={t('settings.notify.dest.form.enabled')} checked={draft.enabled} disabled={busy} data-notify="enabled" onToggle={(next) => (draft.enabled = next)} />
    {#if !editing}
        <Check label={t('settings.notify.dest.form.local_only')} hint={t('settings.notify.dest.form.local_only_hint')} checked={localOnly} disabled={busy} data-notify="local-only"
            onToggle={(next) => (localOnly = next)} />
    {/if}
    <div class="tm__actions">
        <Button disabled={busy} data-notify="cancel" onclick={onCancel}>{t('settings.notify.dest.form.cancel')}</Button>
        <Button type="submit" variant="confirm" disabled={busy || !ready} data-notify="save">{t(editing ? 'settings.notify.dest.form.save' : 'settings.notify.dest.form.add_button')}</Button>
    </div>
</form>
