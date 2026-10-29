
<script lang="ts">
    import type { Translate } from '../sessions/types';
    import IconPicker from '../icon-picker/IconPicker.svelte';
    import { Button, Checkbox, Field, Fold, IconButton, Radio, RadioGroup, Select, State } from '../base';
    import { LAUNCH_MARK_PX, wrapperMark } from '../sessions/agent-marks';
    import type { ConnectionOption, Harness, ModelOption, Posture } from './api';
    import LaunchProfileExamples from './LaunchProfileExamples.svelte';
    import { EXAMPLES } from './examples';
    import { ALL_POSTURES, STRUCTURED, commandOf, lintMissingArgs, postureSupported, scriptOf, type FormState } from './form-model';

    interface Props {
        form: FormState;
        connections: readonly ConnectionOption[];
        models: readonly ModelOption[];
        busy: boolean;
        error: string | null;
        previewModel: string;
        t: Translate;
        onSave: () => void;
        onCancel: () => void;
        onExample?: (id: string) => void;
    }

    let { form = $bindable(), connections, models, busy, error, previewModel = $bindable(), t, onSave, onCancel, onExample }: Props = $props();

    let picking = $state(false);
    let expertOpen = $state(false);
    $effect(() => { expertOpen = form.expert; });

    const structured = $derived(STRUCTURED.includes(form.harness));
    const isCustom = $derived(form.harness === 'custom');
    const harnessOptions = $derived<Harness[]>(Array.from(new Set<Harness>([...STRUCTURED, 'custom', form.harness])));
    const missingArgs = $derived(form.expert && lintMissingArgs(form.script, form.entry));
    const keyedConnections = $derived(connections.filter((c) => c.has_key));
    const onEndpoint = $derived(form.endpointMode === 'connection');

    function addEnv(): void { form.env = [...form.env, { name: '', value: '' }]; }
    function addSecret(): void { form.secrets = [...form.secrets, { name: '', keychain_ref: '' }]; }
</script>

<div class="lp-edit" data-lp-editor>
    {#if form.isNew && onExample}
        <LaunchProfileExamples examples={EXAMPLES} {t} disabled={busy} onUse={onExample} />
    {/if}

    <div class="lp-grid">
        <Field id="lp-label" label={t('launch_profiles.editor.label')} autocomplete="off" spellcheck="false" bind:value={form.label} disabled={busy} />
        <Field id="lp-id" label={t('launch_profiles.editor.id')} data-mono autocomplete="off" spellcheck="false" bind:value={form.id} disabled={busy || !form.isNew}
            help={form.isNew ? t('launch_profiles.editor.id_hint_new') : t('launch_profiles.editor.id_hint_fixed')} />
        <div class="lp-field--wide">
            <Field id="lp-description" label={t('launch_profiles.editor.description')} autocomplete="off" bind:value={form.description} disabled={busy} />
        </div>
        <Select id="lp-harness" label={t('launch_profiles.editor.harness')} bind:value={() => form.harness, (v) => { form.harness = v as Harness; if (v === 'custom') form.expert = true; }} disabled={busy || !form.isNew} help={t('launch_profiles.editor.harness_hint')}>
            {#snippet children()}
                {#each harnessOptions as h (h)}<option value={h}>{h}</option>{/each}
            {/snippet}
        </Select>
        <div class="lp-field">
            <span class="oc-label" id="lp-icon-label">{t('launch_profiles.editor.icon')}</span>
            <div class="lp-icon-row">
                <span class="lp-icon-mark" data-lp-icon-mark>{@html wrapperMark(form.icon, form.harness, LAUNCH_MARK_PX).svg}</span>
                <span class="lp-hint">{form.icon ?? t('launch_profiles.editor.icon_none')}</span>
                <Button size="sm" aria-expanded={picking} data-lp-icon-change onclick={() => (picking = !picking)}>
                    {picking ? t('launch_profiles.editor.icon_done') : t('launch_profiles.editor.icon_change')}
                </Button>
            </div>
        </div>
        {#if picking}
            <div class="lp-field lp-field--wide lp-picker">
                <IconPicker value={form.icon} onChange={(id) => { form.icon = id; picking = false; }} onCancel={() => (picking = false)} {t} autofocus />
            </div>
        {/if}

        {#if structured}
            {#if form.accountMode === 'pinned'}
                <p class="lp-hint lp-hint--warn lp-field--wide" role="note">{t('launch_profiles.editor.pin_unsupported')}</p>
            {/if}

            <div class="lp-field">
                <Select id="lp-endpoint" label={t('launch_profiles.editor.endpoint')}
                    bind:value={() => (onEndpoint ? form.connectionId : ''), (v) => { form.endpointMode = v === '' ? 'native' : 'connection'; form.connectionId = v; }}
                    disabled={busy || form.harness === 'shell'}>
                    {#snippet children()}
                        <option value="">{t('launch_profiles.editor.endpoint_native')}</option>
                        {#each connections as c (c.id)}<option value={c.id} disabled={!c.enabled}>{c.label}</option>{/each}
                    {/snippet}
                </Select>
                {#if onEndpoint && form.connectionId === ''}<span class="lp-hint lp-hint--warn">{t('launch_profiles.editor.endpoint_missing')}</span>{/if}
            </div>

            <Select id="lp-model-mode" label={t('launch_profiles.editor.model')} bind:value={() => form.modelMode, (v) => (form.modelMode = v as FormState['modelMode'])} disabled={busy || form.harness === 'shell'} help={t('launch_profiles.editor.model_hint')}>
                {#snippet children()}
                    <option value="default">{t('launch_profiles.editor.model_default')}</option>
                    <option value="fixed">{t('launch_profiles.editor.model_fixed')}</option>
                    <option value="ask">{t('launch_profiles.editor.model_ask')}</option>
                {/snippet}
            </Select>
            {#if form.modelMode === 'fixed'}
                <div class="lp-field">
                    <Field id="lp-model-value" label={t('launch_profiles.editor.model_id')} data-mono list="lp-models" autocomplete="off" spellcheck="false" bind:value={form.modelValue} disabled={busy} />
                    <datalist id="lp-models">{#each models as m (m.id)}<option value={m.id}>{m.label}</option>{/each}</datalist>
                </div>
            {:else if form.modelMode === 'ask' && onEndpoint}
                <Select id="lp-model-preview" label={t('launch_profiles.editor.model_preview')} data-mono bind:value={previewModel}>
                    {#snippet children()}
                        <option value="">{t('launch_profiles.editor.model_preview_none')}</option>
                        {#each models as m (m.id)}<option value={m.id}>{m.label}</option>{/each}
                    {/snippet}
                </Select>
            {/if}

            <div class="lp-field lp-field--wide">
                <span class="oc-label" id="lp-perms-label">{t('launch_profiles.editor.permissions')}</span>
                <RadioGroup labelledby="lp-perms-label" orientation="horizontal" name="lp-posture" bind:value={() => form.permissions, (v) => (form.permissions = v as Posture)}>
                    {#snippet children()}
                        {#each ALL_POSTURES as p (p)}
                            {@const ok = postureSupported(form.harness, p)}
                            <span class="lp-radio" title={ok ? undefined : t('launch_profiles.editor.posture_unsupported', { harness: form.harness })}>
                                <Radio value={p} label={t(`launch_profiles.posture.${p}`)} disabled={busy || !ok} />
                            </span>
                        {/each}
                    {/snippet}
                </RadioGroup>
                <span class="lp-hint" data-lp-perms-hint>{t('launch_profiles.editor.permissions_hint')}</span>
            </div>
        {:else if isCustom}
            <div class="lp-field--wide">
                <Field id="lp-command" label={t('launch_profiles.editor.command')} data-mono autocomplete="off" spellcheck="false" placeholder="my-agent --flag"
                    bind:value={() => commandOf(form.script), (v) => { form.script = scriptOf(v); form.expert = true; }} disabled={busy}
                    help={t('launch_profiles.editor.command_hint')} />
            </div>
        {:else}
            <p class="lp-hint lp-field--wide">{t('launch_profiles.editor.custom_only', { harness: form.harness })}</p>
        {/if}
    </div>

    {#if structured}
        <div class="lp-fold" data-lp-advanced>
            <Fold label={t('launch_profiles.editor.advanced')}>
                {#snippet children()}
                    <div class="lp-fold__body">
                        <Field id="lp-flags" label={t('launch_profiles.editor.flags')} multiline rows={3} data-mono spellcheck="false" bind:value={form.flagsText} disabled={busy}
                            help={t('launch_profiles.editor.flags_hint')} />

                        <div class="lp-field">
                            <span class="oc-label">{t('launch_profiles.editor.env')}</span>
                            <div class="lp-row oc-colhead" data-lp-colhead>
                                <span class="oc-label">{t('launch_profiles.editor.env_name')}</span>
                                <span class="oc-label">{t('launch_profiles.editor.env_value')}</span>
                                <span class="oc-colhead__ghost lp-ghost" aria-hidden="true"></span>
                            </div>
                            {#each form.env as row, i (i)}
                                <div class="lp-row">
                                    <Field data-mono aria-label={t('launch_profiles.editor.env_name')} placeholder={t('launch_profiles.editor.env_name')} spellcheck="false" bind:value={row.name} />
                                    <Field data-mono aria-label={t('launch_profiles.editor.env_value')} placeholder={t('launch_profiles.editor.env_value')} spellcheck="false" bind:value={row.value} />
                                    <IconButton variant="danger" icon="close" label={t('launch_profiles.editor.row_remove')} data-lp-env-remove onclick={() => (form.env = form.env.filter((_, j) => j !== i))} />
                                </div>
                            {/each}
                            <span class="lp-add"><Button size="sm" data-lp-env-add onclick={addEnv}>{t('launch_profiles.editor.env_add')}</Button></span>
                        </div>

                        <div class="lp-field">
                            <span class="oc-label">{t('launch_profiles.editor.secrets')}</span>
                            <div class="lp-row oc-colhead" data-lp-colhead>
                                <span class="oc-label">{t('launch_profiles.editor.secret_name')}</span>
                                <span class="oc-label">{t('launch_profiles.editor.secret_ref')}</span>
                                <span class="oc-colhead__ghost lp-ghost" aria-hidden="true"></span>
                            </div>
                            {#each form.secrets as row, i (i)}
                                <div class="lp-row">
                                    <Field data-mono aria-label={t('launch_profiles.editor.secret_name')} placeholder={t('launch_profiles.editor.secret_name')} spellcheck="false" bind:value={row.name} />
                                    <Select aria-label={t('launch_profiles.editor.secret_ref')} bind:value={row.keychain_ref}>
                                        {#snippet children()}
                                            <option value="">{t('launch_profiles.editor.secret_ref_pick')}</option>
                                            {#each keyedConnections as c (c.id)}<option value={c.id}>{c.label} ({c.key_hint})</option>{/each}
                                            {#if row.keychain_ref && !keyedConnections.some((c) => c.id === row.keychain_ref)}<option value={row.keychain_ref}>{row.keychain_ref}</option>{/if}
                                        {/snippet}
                                    </Select>
                                    <IconButton variant="danger" icon="close" label={t('launch_profiles.editor.row_remove')} data-lp-secret-remove onclick={() => (form.secrets = form.secrets.filter((_, j) => j !== i))} />
                                </div>
                            {/each}
                            <span class="lp-add"><Button size="sm" data-lp-secret-add onclick={addSecret}>{t('launch_profiles.editor.secret_add')}</Button></span>
                            <span class="lp-hint">{t('launch_profiles.editor.secrets_hint')}</span>
                        </div>

                        <Checkbox label={t('launch_profiles.editor.shell_profile')} bind:checked={form.shellProfile} disabled={busy} />

                        <Field id="lp-before" label={t('launch_profiles.editor.before_launch')} multiline rows={2} data-mono spellcheck="false" bind:value={form.beforeLaunch} disabled={busy}
                            help={t('launch_profiles.editor.before_launch_hint')} />
                    </div>
                {/snippet}
            </Fold>
        </div>
    {/if}

    {#if !isCustom}
    <div class="lp-fold" data-lp-expert>
        <Fold label={t('launch_profiles.editor.expert')} bind:open={expertOpen}>
            {#snippet children()}
                <div class="lp-fold__body">
                    <Checkbox label={t('launch_profiles.editor.expert_on')} bind:checked={form.expert} disabled={busy} />
                    {#if form.expert}
                        <Field id="lp-script" label={t('launch_profiles.editor.script')} multiline rows={8} data-mono spellcheck="false" placeholder={'claude "$@"'} bind:value={form.script} disabled={busy} />
                        <Field id="lp-entry" label={t('launch_profiles.editor.entry')} data-mono spellcheck="false" bind:value={form.entry} disabled={busy}
                            help={t('launch_profiles.editor.entry_hint')} />
                        {#if missingArgs}
                            <State inline kind="warn" role="alert" title={t('launch_profiles.editor.lint_args')} data-lp-lint />
                            <Checkbox label={t('launch_profiles.editor.lint_ack')} bind:checked={form.ackNoArgs} disabled={busy} />
                        {/if}
                    {/if}
                </div>
            {/snippet}
        </Fold>
    </div>
    {/if}

    {#if error}<State inline kind="error" title={error} data-lp-error />{/if}

    <div class="lp-actions">
        <Button variant="confirm" disabled={busy} onclick={onSave} data-lp-save>
            {busy ? t('launch_profiles.editor.saving') : t('launch_profiles.editor.save')}
        </Button>
        <Button disabled={busy} onclick={onCancel} data-lp-cancel>{t('launch_profiles.editor.cancel')}</Button>
    </div>
</div>

<style>
  @layer components {
    .lp-edit { display: flex; flex-direction: column; min-width: 0; }
    .lp-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px 12px; }
    .lp-field { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
    .lp-field--wide { grid-column: 1 / -1; }
    .lp-hint { color: var(--pl-dim); font-size: 11px; overflow-wrap: anywhere; }
    .lp-hint--warn { color: var(--pl-warn); }
    .lp-edit :global(:is(input, select, textarea)[data-field][data-mono]) { font-family: var(--pl-mono); }
    .lp-icon-mark { display: inline-flex; flex: none; width: 24px; height: 24px; line-height: 0; color: var(--pl-muted); }
    .lp-icon-row { display: flex; align-items: center; gap: 8px; min-height: 32px; }
    .lp-picker { max-width: 420px; color: var(--pl-text); }
    .lp-radio { display: inline-flex; }
    .lp-fold { margin-top: 12px; border-top: 1px solid var(--pl-line-quiet); }
    .lp-fold__body { display: flex; flex-direction: column; gap: 10px; padding-bottom: 8px; }
    .lp-row { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) auto; gap: 6px; align-items: center; }
    .lp-ghost { width: var(--oc-control-h-xs); }
    .lp-add { align-self: flex-start; }
    .lp-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
    @media (max-width: 520px) { .lp-row { grid-template-columns: minmax(0, 1fr) auto; } .lp-row > :first-child { grid-column: 1 / -1; } }
  }
</style>
