
<script lang="ts">
    import type { Translate } from '../sessions/types';
    import IconPicker from '../icon-picker/IconPicker.svelte';
    import { LAUNCH_MARK_PX, wrapperMark } from '../sessions/agent-marks';
    import type { AccountOption, ConnectionOption, ModelOption } from './api';
    import { ALL_POSTURES, STRUCTURED, lintMissingArgs, postureSupported, type FormState } from './form-model';

    interface Props {
        form: FormState;
        accounts: readonly AccountOption[];
        connections: readonly ConnectionOption[];
        models: readonly ModelOption[];
        busy: boolean;
        error: string | null;
        previewModel: string;
        t: Translate;
        onSave: () => void;
        onCancel: () => void;
    }

    let { form = $bindable(), accounts, connections, models, busy, error, previewModel = $bindable(), t, onSave, onCancel }: Props = $props();

    let picking = $state(false);

    const structured = $derived(STRUCTURED.includes(form.harness));
    const missingArgs = $derived(form.expert && lintMissingArgs(form.script, form.entry));
    const keyedConnections = $derived(connections.filter((c) => c.has_key));
    const onEndpoint = $derived(form.endpointMode === 'connection');

    function addEnv(): void { form.env = [...form.env, { name: '', value: '' }]; }
    function addSecret(): void { form.secrets = [...form.secrets, { name: '', keychain_ref: '' }]; }
</script>

<div class="lp-edit" data-lp-editor>

    <div class="lp-grid">
        <div class="lp-field">
            <label class="lp-label" for="lp-label">{t('launch_profiles.editor.label')}</label>
            <input id="lp-label" class="lp-input" type="text" autocomplete="off" spellcheck="false" bind:value={form.label} disabled={busy} />
        </div>
        <div class="lp-field">
            <label class="lp-label" for="lp-id">{t('launch_profiles.editor.id')}</label>
            <input id="lp-id" class="lp-input lp-input--mono" type="text" autocomplete="off" spellcheck="false" bind:value={form.id} disabled={busy || !form.isNew} />
            <span class="lp-hint">{form.isNew ? t('launch_profiles.editor.id_hint_new') : t('launch_profiles.editor.id_hint_fixed')}</span>
        </div>
        <div class="lp-field lp-field--wide">
            <label class="lp-label" for="lp-description">{t('launch_profiles.editor.description')}</label>
            <input id="lp-description" class="lp-input" type="text" autocomplete="off" bind:value={form.description} disabled={busy} />
        </div>
        <div class="lp-field">
            <label class="lp-label" for="lp-harness">{t('launch_profiles.editor.harness')}</label>
            <select id="lp-harness" class="lp-input" bind:value={form.harness} disabled={busy || !form.isNew}>
                {#each (STRUCTURED.includes(form.harness) ? STRUCTURED : [...STRUCTURED, form.harness]) as h (h)}<option value={h}>{h}</option>{/each}
            </select>
        </div>
        <div class="lp-field">
            <span class="lp-label" id="lp-icon-label">{t('launch_profiles.editor.icon')}</span>
            <div class="lp-icon-row">
                <span class="lp-icon-mark" data-lp-icon-mark>{@html wrapperMark(form.icon, form.harness, LAUNCH_MARK_PX).svg}</span>
                <span class="lp-hint">{form.icon ?? t('launch_profiles.editor.icon_none')}</span>
                <button type="button" class="oc-btn oc-btn--sm" aria-expanded={picking} onclick={() => (picking = !picking)}>
                    {picking ? t('launch_profiles.editor.icon_done') : t('launch_profiles.editor.icon_change')}
                </button>
            </div>
        </div>
        {#if picking}
            <div class="lp-field lp-field--wide lp-picker">
                <IconPicker value={form.icon} onChange={(id) => { form.icon = id; picking = false; }} onCancel={() => (picking = false)} {t} autofocus />
            </div>
        {/if}

        {#if structured}
            <div class="lp-field">
                <label class="lp-label" for="lp-account">{t('launch_profiles.editor.account')}</label>
                <select id="lp-account" class="lp-input"
                    value={form.accountMode === 'pinned' ? form.accountId : ''}
                    disabled={busy || form.harness !== 'claude'}
                    onchange={(e) => {
                        const v = (e.currentTarget as HTMLSelectElement).value;
                        form.accountMode = v === '' ? 'follow_active' : 'pinned';
                        form.accountId = v;
                    }}>
                    <option value="">{t('launch_profiles.editor.account_follow')}</option>
                    {#each accounts as a (a.id)}<option value={a.id}>{a.name}</option>{/each}
                </select>
                {#if form.harness !== 'claude'}<span class="lp-hint">{t('launch_profiles.editor.account_claude_only')}</span>{/if}
            </div>

            <div class="lp-field">
                <label class="lp-label" for="lp-endpoint">{t('launch_profiles.editor.endpoint')}</label>
                <select id="lp-endpoint" class="lp-input"
                    value={onEndpoint ? form.connectionId : ''}
                    disabled={busy || form.harness === 'shell'}
                    onchange={(e) => {
                        const v = (e.currentTarget as HTMLSelectElement).value;
                        form.endpointMode = v === '' ? 'native' : 'connection';
                        form.connectionId = v;
                    }}>
                    <option value="">{t('launch_profiles.editor.endpoint_native')}</option>
                    {#each connections as c (c.id)}<option value={c.id} disabled={!c.enabled}>{c.label}</option>{/each}
                </select>
                {#if onEndpoint && form.connectionId === ''}<span class="lp-hint lp-hint--warn">{t('launch_profiles.editor.endpoint_missing')}</span>{/if}
            </div>

            <div class="lp-field">
                <label class="lp-label" for="lp-model-mode">{t('launch_profiles.editor.model')}</label>
                <select id="lp-model-mode" class="lp-input" bind:value={form.modelMode} disabled={busy || form.harness === 'shell'}>
                    <option value="default">{t('launch_profiles.editor.model_default')}</option>
                    <option value="fixed">{t('launch_profiles.editor.model_fixed')}</option>
                    <option value="ask">{t('launch_profiles.editor.model_ask')}</option>
                </select>
            </div>
            {#if form.modelMode === 'fixed'}
                <div class="lp-field">
                    <label class="lp-label" for="lp-model-value">{t('launch_profiles.editor.model_id')}</label>
                    <input id="lp-model-value" class="lp-input lp-input--mono" type="text" list="lp-models" autocomplete="off" spellcheck="false" bind:value={form.modelValue} disabled={busy} />
                    <datalist id="lp-models">{#each models as m (m.id)}<option value={m.id}>{m.label}</option>{/each}</datalist>
                </div>
            {:else if form.modelMode === 'ask' && onEndpoint}
                <div class="lp-field">
                    <label class="lp-label" for="lp-model-preview">{t('launch_profiles.editor.model_preview')}</label>
                    <select id="lp-model-preview" class="lp-input lp-input--mono" bind:value={previewModel}>
                        <option value="">{t('launch_profiles.editor.model_preview_none')}</option>
                        {#each models as m (m.id)}<option value={m.id}>{m.label}</option>{/each}
                    </select>
                </div>
            {/if}

            <fieldset class="lp-field lp-field--wide lp-perms">
                <legend class="lp-label">{t('launch_profiles.editor.permissions')}</legend>
                {#each ALL_POSTURES as p (p)}
                    {@const ok = postureSupported(form.harness, p)}
                    <label class="lp-radio" class:lp-radio--off={!ok} title={ok ? '' : t('launch_profiles.editor.posture_unsupported', { harness: form.harness })}>
                        <input type="radio" name="lp-posture" value={p} bind:group={form.permissions} disabled={busy || !ok} />
                        {t(`launch_profiles.posture.${p}`)}
                    </label>
                {/each}
            </fieldset>
        {:else}
            <p class="lp-hint lp-field--wide">{t('launch_profiles.editor.custom_only', { harness: form.harness })}</p>
        {/if}
    </div>

    {#if structured}
        <details class="lp-fold" data-lp-advanced>
            <summary class="lp-fold__head">{t('launch_profiles.editor.advanced')}</summary>
            <div class="lp-fold__body">
                <div class="lp-field">
                    <label class="lp-label" for="lp-flags">{t('launch_profiles.editor.flags')}</label>
                    <textarea id="lp-flags" class="lp-input lp-input--mono" rows="3" spellcheck="false" bind:value={form.flagsText} disabled={busy}></textarea>
                    <span class="lp-hint">{t('launch_profiles.editor.flags_hint')}</span>
                </div>

                <div class="lp-field">
                    <span class="lp-label">{t('launch_profiles.editor.env')}</span>
                    <div class="lp-row oc-colhead" data-lp-colhead>
                        <span class="oc-label">{t('launch_profiles.editor.env_name')}</span>
                        <span class="oc-label">{t('launch_profiles.editor.env_value')}</span>
                        <span class="oc-btn oc-btn--sm oc-colhead__ghost" aria-hidden="true">x</span>
                    </div>
                    {#each form.env as row, i (i)}
                        <div class="lp-row">
                            <input class="lp-input lp-input--mono" type="text" aria-label={t('launch_profiles.editor.env_name')} placeholder={t('launch_profiles.editor.env_name')} spellcheck="false" bind:value={row.name} />
                            <input class="lp-input lp-input--mono" type="text" aria-label={t('launch_profiles.editor.env_value')} placeholder={t('launch_profiles.editor.env_value')} spellcheck="false" bind:value={row.value} />
                            <button type="button" class="oc-btn oc-btn--sm" aria-label={t('launch_profiles.editor.row_remove')} onclick={() => (form.env = form.env.filter((_, j) => j !== i))}>x</button>
                        </div>
                    {/each}
                    <button type="button" class="oc-btn oc-btn--sm lp-add" onclick={addEnv}>{t('launch_profiles.editor.env_add')}</button>
                </div>

                <div class="lp-field">
                    <span class="lp-label">{t('launch_profiles.editor.secrets')}</span>
                    <div class="lp-row oc-colhead" data-lp-colhead>
                        <span class="oc-label">{t('launch_profiles.editor.secret_name')}</span>
                        <span class="oc-label">{t('launch_profiles.editor.secret_ref')}</span>
                        <span class="oc-btn oc-btn--sm oc-colhead__ghost" aria-hidden="true">x</span>
                    </div>
                    {#each form.secrets as row, i (i)}
                        <div class="lp-row">
                            <input class="lp-input lp-input--mono" type="text" aria-label={t('launch_profiles.editor.secret_name')} placeholder={t('launch_profiles.editor.secret_name')} spellcheck="false" bind:value={row.name} />
                            <select class="lp-input" aria-label={t('launch_profiles.editor.secret_ref')} bind:value={row.keychain_ref}>
                                <option value="">{t('launch_profiles.editor.secret_ref_pick')}</option>
                                {#each keyedConnections as c (c.id)}<option value={c.id}>{c.label} ({c.key_hint})</option>{/each}
                                {#if row.keychain_ref && !keyedConnections.some((c) => c.id === row.keychain_ref)}<option value={row.keychain_ref}>{row.keychain_ref}</option>{/if}
                            </select>
                            <button type="button" class="oc-btn oc-btn--sm" aria-label={t('launch_profiles.editor.row_remove')} onclick={() => (form.secrets = form.secrets.filter((_, j) => j !== i))}>x</button>
                        </div>
                    {/each}
                    <button type="button" class="oc-btn oc-btn--sm lp-add" onclick={addSecret}>{t('launch_profiles.editor.secret_add')}</button>
                    <span class="lp-hint">{t('launch_profiles.editor.secrets_hint')}</span>
                </div>

                <label class="lp-check"><input type="checkbox" bind:checked={form.shellProfile} disabled={busy} /> {t('launch_profiles.editor.shell_profile')}</label>

                <div class="lp-field">
                    <label class="lp-label" for="lp-before">{t('launch_profiles.editor.before_launch')}</label>
                    <textarea id="lp-before" class="lp-input lp-input--mono" rows="2" spellcheck="false" bind:value={form.beforeLaunch} disabled={busy}></textarea>
                    <span class="lp-hint">{t('launch_profiles.editor.before_launch_hint')}</span>
                </div>
            </div>
        </details>
    {/if}

    <details class="lp-fold" data-lp-expert open={form.expert}>
        <summary class="lp-fold__head">{t('launch_profiles.editor.expert')}</summary>
        <div class="lp-fold__body">
            <label class="lp-check"><input type="checkbox" bind:checked={form.expert} disabled={busy} /> {t('launch_profiles.editor.expert_on')}</label>
            {#if form.expert}
                <div class="lp-field">
                    <label class="lp-label" for="lp-script">{t('launch_profiles.editor.script')}</label>
                    <textarea id="lp-script" class="lp-input lp-input--mono" rows="8" spellcheck="false" placeholder={'claude "$@"'} bind:value={form.script} disabled={busy}></textarea>
                </div>
                <div class="lp-field">
                    <label class="lp-label" for="lp-entry">{t('launch_profiles.editor.entry')}</label>
                    <input id="lp-entry" class="lp-input lp-input--mono" type="text" spellcheck="false" bind:value={form.entry} disabled={busy} />
                    <span class="lp-hint">{t('launch_profiles.editor.entry_hint')}</span>
                </div>
                {#if missingArgs}
                    <p class="lp-warn" role="alert" data-lp-lint>{t('launch_profiles.editor.lint_args')}</p>
                    <label class="lp-check"><input type="checkbox" bind:checked={form.ackNoArgs} disabled={busy} /> {t('launch_profiles.editor.lint_ack')}</label>
                {/if}
            {/if}
        </div>
    </details>

    {#if error}<p class="lp-error" role="alert" data-lp-error>{error}</p>{/if}

    <div class="lp-actions">
        <button type="button" class="oc-btn oc-btn--confirm" disabled={busy} onclick={onSave} data-lp-save>
            {busy ? t('launch_profiles.editor.saving') : t('launch_profiles.editor.save')}
        </button>
        <button type="button" class="oc-btn" disabled={busy} onclick={onCancel}>{t('launch_profiles.editor.cancel')}</button>
    </div>
</div>

<style>
  @layer components {
    .lp-edit { padding: 12px; border-top: 1px solid var(--pl-focus); background: var(--pl-raised); min-width: 0; }
    .lp-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px 12px; }
    .lp-field { display: flex; flex-direction: column; gap: 3px; min-width: 0; margin: 0; padding: 0; border: 0; }
    .lp-field--wide { grid-column: 1 / -1; }
    .lp-label { color: var(--pl-dim); font-size: var(--oc-fs-micro, 10px); letter-spacing: var(--oc-tracking-label, 0.6px); text-transform: uppercase; }
    .lp-hint { color: var(--pl-dim); font-size: 11px; overflow-wrap: anywhere; }
    .lp-hint--warn { color: var(--pl-warn); }
    .lp-input { width: 100%; min-width: 0; min-height: 32px; padding: 6px 8px; border: 1px solid var(--pl-line-panel); border-radius: var(--pl-radius-sm); background: var(--pl-ground); color: var(--pl-text); font-size: 12px; font-family: inherit; box-sizing: border-box; }
    .lp-input--mono { font-family: var(--pl-mono); }
    textarea.lp-input { resize: vertical; }
    .lp-icon-mark { display: inline-flex; flex: none; width: 24px; height: 24px; line-height: 0; color: var(--pl-muted); }
    .lp-icon-row { display: flex; align-items: center; gap: 8px; min-height: 32px; }
    .lp-picker { max-width: 420px; color: var(--pl-text); }
    .lp-perms { flex-direction: row; flex-wrap: wrap; gap: 6px 16px; }
    .lp-perms .lp-label { width: 100%; padding: 0; }
    .lp-radio, .lp-check { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--pl-text); }
    .lp-radio--off { color: var(--pl-dim); opacity: 0.6; }
    .lp-fold { margin-top: 12px; border-top: 1px solid var(--pl-line-quiet); }
    .lp-fold__head { padding: 8px 0; color: var(--pl-muted); font-size: var(--oc-fs-micro, 10px); letter-spacing: var(--oc-tracking-label, 0.6px); text-transform: uppercase; cursor: pointer; }
    .lp-fold__body { display: flex; flex-direction: column; gap: 10px; padding-bottom: 8px; }
    .lp-row { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) auto; gap: 6px; align-items: center; }
    .lp-add { align-self: flex-start; }
    .lp-warn, .lp-error { margin: 8px 0 0; padding: 6px 8px; border-left: 2px solid var(--pl-warn); background: var(--pl-ground); color: var(--pl-text); font-size: 12px; overflow-wrap: anywhere; }
    .lp-error { border-left-color: var(--pl-high); }
    .lp-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
    @media (max-width: 520px) { .lp-row { grid-template-columns: minmax(0, 1fr) auto; } .lp-row > :first-child { grid-column: 1 / -1; } }
  }
</style>
