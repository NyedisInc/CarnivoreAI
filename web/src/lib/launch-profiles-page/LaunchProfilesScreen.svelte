
<script lang="ts">
    import { captureOpener, restoreOpenerFocus } from '../dialog-frame/opener-focus';
    import { onMount } from 'svelte';
    import { registerPageDirty } from '../menu-page/menu-page-dirty';
    import '../ledger/ledger-chrome.css';
    import Page from '../../opscenter/ui/Page.svelte';
    import { isInset } from '../../opscenter/ui/page-inset';
    import { t as appT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import { LAUNCH_MARK_PX, providerMark, wrapperMark } from '../sessions/agent-marks';
    import { openModal } from '../modal';
    import ImportProfileModal from './ImportProfileModal.svelte';
    import LaunchProfileEditor from './LaunchProfileEditor.svelte';
    import {
        createLaunchProfilesApi, deleteRefusal, errorText,
        type AccountOption, type CheckResult, type ConnectionOption, type DeleteRefusal, type LaunchProfilesApi,
        type ModelOption, type Preview, type ProfileRow, type UsageResult,
    } from './api';
    import {
        TEMPLATES, blankForm, formToProfile, profileToForm, slugFromLabel, templateForm, uniqueId, type FormState,
    } from './form-model';

    interface Props {
        api?: LaunchProfilesApi;
        t?: Translate;
        embedded?: boolean;
    }
    const { api: injected, t = appT, embedded = false }: Props = $props();
    // svelte-ignore state_referenced_locally
    const api: LaunchProfilesApi = injected ?? createLaunchProfilesApi();

    // svelte-ignore state_referenced_locally
    let open = $state(embedded);
    let opener: HTMLElement | null = null;
    let rows = $state<ProfileRow[]>([]);
    let revision = $state(0);
    let loading = $state(false);
    let failure = $state<string | null>(null);
    let accounts = $state<AccountOption[]>([]);
    let connections = $state<ConnectionOption[]>([]);
    let models = $state<ModelOption[]>([]);
    let form = $state<FormState | null>(null);
    let busy = $state(false);
    let saveError = $state<string | null>(null);
    let notice = $state<{ text: string; error: boolean } | null>(null);
    let previewModel = $state('');
    let preview = $state<Preview | null>(null);
    let previewError = $state<string | null>(null);
    let check = $state<CheckResult | null>(null);
    let usage = $state<UsageResult | null>(null);
    let refusal = $state<DeleteRefusal | null>(null);
    let moveTo = $state('');
    let pickingTemplate = $state(false);

    const selected = $derived(form && !form.isNew ? (rows.find((r) => r.id === form!.id) ?? null) : null);
    const inset = isInset();
    const taken = $derived(new Set(rows.map((r) => r.id)));

    async function load(): Promise<void> {
        loading = true;
        try { const out = await api.list(); rows = out.profiles; revision = out.revision; failure = null; }
        catch (err) { failure = errorText(err); }
        loading = false;
    }

    async function loadOptions(): Promise<void> {
        accounts = await api.accounts().catch(() => []);
        connections = await api.connections().catch(() => []);
    }

    export function show(): void {
        if (open) return;
        opener = captureOpener();
        open = true;
        void load();
        void loadOptions();
    }

    export function close(): void {
        if (!open || embedded) return;
        open = false; form = null; notice = null;
        restoreOpenerFocus(opener);
        opener = null;
    }

    export function isOpen(): boolean { return open; }

    onMount(() => {
        if (embedded) { void load(); void loadOptions(); }
        return registerPageDirty('settings', () => formDirty());
    });

    let baseline = '';

    function adopt(next: FormState): void {
        form = next;
        baseline = JSON.stringify(next);
    }

    function formDirty(): boolean {
        return form !== null && JSON.stringify(form) !== baseline;
    }

    function resetDetail(): void {
        saveError = null; notice = null; check = null; usage = null; refusal = null; moveTo = ''; preview = null; previewError = null; previewModel = '';
    }

    function select(row: ProfileRow): void {
        resetDetail();
        adopt(profileToForm(row));
        api.usage(row.id).then((u) => { if (form?.id === row.id) usage = u; }).catch(() => { usage = null; });
    }

    function startTemplate(id: string): void {
        resetDetail();
        pickingTemplate = false;
        const tpl = TEMPLATES.find((x) => x.id === id) ?? TEMPLATES[0]!;
        const label = t(`launch_profiles.template.${tpl.id}`);
        const next = templateForm(tpl, label, connections);
        adopt({ ...next, id: uniqueId(next.id, taken) });
    }

    function duplicate(): void {
        if (!selected) return;
        const label = t('launch_profiles.action.copy_label', { name: selected.label });
        const copy = { ...profileToForm(selected), isNew: true, default: false, label, id: uniqueId(slugFromLabel(label), taken) };
        resetDetail();
        adopt(copy);
    }

    let previewSeq = 0;
    $effect(() => {
        if (!form) return;
        const draft = formToProfile(form);
        const model = previewModel || null;
        if (!draft.id) { preview = null; previewError = null; return; }
        const seq = ++previewSeq;
        const timer = setTimeout(async () => {
            try {
                const out = await api.previewDraft(draft, model);
                if (seq === previewSeq) { preview = out; previewError = null; }
            } catch (err) {
                if (seq === previewSeq) { preview = null; previewError = errorText(err); }
            }
        }, 350);
        return () => clearTimeout(timer);
    });

    $effect(() => {
        const id = form && form.endpointMode === 'connection' ? form.connectionId : '';
        if (!id) { models = []; return; }
        let live = true;
        api.models(id).then((m) => { if (live) models = m; }).catch(() => { if (live) models = []; });
        return () => { live = false; };
    });

    async function save(): Promise<void> {
        if (!form || busy) return;
        busy = true; saveError = null;
        const profile = formToProfile(form);
        try {
            const out = form.isNew ? await api.create(profile, revision) : await api.replace(profile, revision);
            await load();
            const row = rows.find((r) => r.id === out.profile.id);
            if (row) select(row);
            notice = { text: t('launch_profiles.editor.saved'), error: false };
        } catch (err) {
            saveError = errorText(err);
        }
        busy = false;
    }

    async function runCheck(): Promise<void> {
        if (!selected) return;
        check = null; notice = null;
        try { check = await api.check(selected.id); }
        catch (err) { notice = { text: errorText(err), error: true }; }
    }

    async function makeDefault(): Promise<void> {
        if (!selected) return;
        try { await api.setDefault(selected.id); await load(); const row = rows.find((r) => r.id === selected!.id); if (row) select(row); }
        catch (err) { notice = { text: errorText(err), error: true }; }
    }

    async function remove(): Promise<void> {
        if (!selected) return;
        const id = selected.id;
        try {
            await api.remove(id);
            form = null; refusal = null; resetDetail();
            await load();
            notice = { text: t('launch_profiles.action.deleted', { name: id }), error: false };
        } catch (err) {
            const r = deleteRefusal(err);
            if (r) { refusal = r; moveTo = ''; } else notice = { text: errorText(err), error: true };
        }
    }

    async function moveThenDelete(): Promise<void> {
        if (!selected || !moveTo) return;
        try { await api.move(selected.id, moveTo); refusal = null; await remove(); }
        catch (err) { notice = { text: errorText(err), error: true }; }
    }

    async function exportOne(): Promise<void> {
        if (!selected) return;
        try {
            const doc = await api.exportDoc(selected.id);
            const url = URL.createObjectURL(new Blob([JSON.stringify(doc, null, 2)], { type: 'application/json' }));
            const a = document.createElement('a');
            a.href = url; a.download = `${selected.id}.launch-profile.json`;
            a.click();
            URL.revokeObjectURL(url);
        } catch (err) { notice = { text: errorText(err), error: true }; }
    }

    async function importOne(): Promise<void> {
        const id = await openModal<string, { api: LaunchProfilesApi; t: Translate }>(ImportProfileModal, { api, t });
        if (!id) return;
        await load();
        const row = rows.find((r) => r.id === id);
        if (row) select(row);
        notice = { text: t('launch_profiles.import.done', { name: id }), error: false };
    }

    function facts(r: ProfileRow): string {
        const account = r.account.mode === 'pinned' ? (accounts.find((a) => a.id === r.account.account_id)?.name ?? r.account.account_id ?? '') : t('launch_profiles.list.follow');
        return `${account} / ${r.summary.model}`;
    }

    const moveTargets = $derived(selected ? rows.filter((r) => r.harness === selected!.harness && r.id !== selected!.id) : []);
</script>

{#if open}
    {#snippet pageActions()}
        <button type="button" class="oc-btn" data-lp-import-open onclick={() => void importOne()}>{t('launch_profiles.page.import')}</button>
        <button type="button" class="oc-btn oc-btn--confirm" data-lp-new aria-expanded={pickingTemplate} onclick={() => (pickingTemplate = !pickingTemplate)}>{t('launch_profiles.page.new')}</button>
    {/snippet}

    <Page class="pledger lp-page" title={t('launch_profiles.page.title')} count={rows.length > 0 ? t('launch_profiles.page.count', { count: rows.length }) : undefined}
        onClose={embedded ? undefined : close} closeLabel={t('launch_profiles.page.close')} actions={pageActions} {embedded}>
        <div class="oc-page__scroll">
            <div class="oc-page__main oc-page__main--stack">
                {#if failure}<p class="lp-error" role="alert" data-lp-failure>{t('launch_profiles.page.failed', { reason: failure })}</p>{/if}
                {#if notice}<p class={notice.error ? 'lp-error' : 'lp-note'} role={notice.error ? 'alert' : 'status'} data-lp-notice>{notice.text}</p>{/if}

                {#if pickingTemplate}
                    <div class="pl-panel lp-templates" data-lp-templates>
                        <p class="pl-label lp-templates__head">{t('launch_profiles.page.templates')}</p>
                        <div class="lp-templates__list">
                            {#each TEMPLATES as tpl (tpl.id)}
                                <button type="button" class="oc-btn" data-lp-template={tpl.id} onclick={() => startTemplate(tpl.id)}>{t(`launch_profiles.template.${tpl.id}`)}</button>
                            {/each}
                        </div>
                    </div>
                {/if}

                <div class="lp-split" class:lp-split--solo={!form}>
                    <section class="pl-panel lp-list" aria-label={t('launch_profiles.page.title')}>
                        {#if !inset}<header class="pl-titlebar"><h2 class="pl-title">{t('launch_profiles.list.title')}</h2></header>{/if}
                        {#if rows.length === 0 && !loading}<p class="lp-empty">{t('launch_profiles.list.empty')}</p>{/if}
                        <ul class="lp-rows">
                            {#each rows as r (r.id)}
                                {@const mark = wrapperMark(r.icon, r.harness, LAUNCH_MARK_PX)}
                                <li>
                                    <button type="button" class="lp-item" class:lp-item--on={form?.id === r.id && !form?.isNew} data-lp-row={r.id} onclick={() => select(r)}>
                                        <span class="lp-item__mark" role="img" aria-label={providerMark(r.harness).label} data-mark-source={mark.source}>{@html mark.svg}</span>
                                        <span class="lp-item__main">
                                            <span class="lp-item__label">
                                                <span class="lp-item__name">{r.label}</span>
                                                {#if r.default}<span class="lp-badge lp-badge--default" data-lp-default>{t('launch_profiles.list.default')}</span>{/if}
                                            </span>
                                            <span class="lp-item__sub">
                                                <span class="lp-item__facts">{facts(r)}</span>
                                                {#if r.permissions !== 'harness_default'}<span class="lp-badge lp-badge--perm" class:lp-badge--warn={r.permissions === 'skip_all'} data-lp-perm={r.permissions}>{r.summary.permissions_badge}</span>{/if}
                                            </span>
                                        </span>
                                    </button>
                                </li>
                            {/each}
                        </ul>
                        {#if !form && rows.length > 0}<p class="lp-note" data-lp-pick>{t('launch_profiles.page.pick')}</p>{/if}
                    </section>

                    <div class="lp-detail" class:lp-detail--none={!form}>
                        {#if form}
                            <section class="pl-panel">
                                <header class="pl-titlebar lp-head">
                                    <h2 class="pl-title">{form.isNew ? t('launch_profiles.editor.new_title') : form.label}</h2>
                                    {#if selected}
                                        <div class="lp-tools">
                                            <button type="button" class="oc-btn oc-btn--sm" data-lp-check onclick={() => void runCheck()}>{t('launch_profiles.action.check')}</button>
                                            <button type="button" class="oc-btn oc-btn--sm" data-lp-duplicate onclick={duplicate}>{t('launch_profiles.action.duplicate')}</button>
                                            {#if !selected.default}<button type="button" class="oc-btn oc-btn--sm" data-lp-make-default onclick={() => void makeDefault()}>{t('launch_profiles.action.make_default')}</button>{/if}
                                            <button type="button" class="oc-btn oc-btn--sm" data-lp-export onclick={() => void exportOne()}>{t('launch_profiles.action.export')}</button>
                                            <button type="button" class="oc-btn oc-btn--sm lp-danger" data-lp-delete onclick={() => void remove()}>{t('launch_profiles.action.delete')}</button>
                                        </div>
                                    {/if}
                                </header>

                                {#if refusal}
                                    <div class="lp-refusal" role="alert" data-lp-refusal>
                                        <p class="lp-refusal__text">{refusal.message}</p>
                                        {#each Object.entries(refusal.counts).filter(([, n]) => n > 0) as [kind, n] (kind)}
                                            <p class="lp-refusal__count" data-lp-count={kind}>{kind.replace(/_/g, ' ')}: {n}</p>
                                        {/each}
                                        {#if refusal.code === 'in_use'}
                                            <div class="lp-row">
                                                <select class="lp-select" aria-label={t('launch_profiles.action.move_to')} bind:value={moveTo} data-lp-move-to>
                                                    <option value="">{t('launch_profiles.action.move_to')}</option>
                                                    {#each moveTargets as r (r.id)}<option value={r.id}>{r.label}</option>{/each}
                                                </select>
                                                <button type="button" class="oc-btn oc-btn--sm" disabled={!moveTo} data-lp-move onclick={() => void moveThenDelete()}>{t('launch_profiles.action.move_delete')}</button>
                                            </div>
                                            {#if moveTargets.length === 0}<p class="lp-note">{t('launch_profiles.action.no_move_target', { harness: selected?.harness ?? '' })}</p>{/if}
                                        {/if}
                                    </div>
                                {/if}

                                {#if check}
                                    <div class="lp-result" data-lp-check-result>
                                        <p class="pl-label">{t('launch_profiles.check.title')}</p>
                                        <p class="lp-check__line">{t('launch_profiles.check.binary', { status: check.binary.status })}{check.binary.output ? `: ${check.binary.output}` : ''}</p>
                                        {#if check.endpoint}<p class="lp-check__line">{t(check.endpoint.ok ? 'launch_profiles.check.endpoint_ok' : 'launch_profiles.check.endpoint_failed', { models: check.endpoint.models, detail: check.endpoint.detail ?? '' })}</p>{/if}
                                    </div>
                                {/if}

                                <LaunchProfileEditor bind:form bind:previewModel {accounts} {connections} {models} {busy} error={saveError} {t} onSave={() => void save()} onCancel={() => { form = null; resetDetail(); }} />
                            </section>

                            <section class="pl-panel" data-lp-preview>
                                <header class="pl-titlebar"><h2 class="pl-title">{t('launch_profiles.preview.title')}</h2></header>
                                <div class="lp-preview">
                                    {#if previewError}
                                        <p class="lp-error" role="status" data-lp-preview-error>{previewError}</p>
                                    {:else if preview}
                                        <p class="pl-label">{t('launch_profiles.preview.command')}</p>
                                        <pre class="lp-code" data-lp-preview-command>{preview.command}</pre>
                                        {#if preview.env_set.length}
                                            <p class="pl-label">{t('launch_profiles.preview.env')}</p>
                                            <pre class="lp-code" data-lp-preview-env>{preview.env_set.map((e) => `${e.name}=${e.value}`).join('\n')}</pre>
                                        {/if}
                                        {#if preview.env_unset.length}
                                            <p class="pl-label">{t('launch_profiles.preview.unset')}</p>
                                            <pre class="lp-code">{preview.env_unset.join('\n')}</pre>
                                        {/if}
                                        {#if preview.secrets.length}
                                            <p class="pl-label">{t('launch_profiles.preview.secrets')}</p>
                                            <pre class="lp-code" data-lp-preview-secrets>{preview.secrets.map((s) => `${s.name} <- ${s.keychain_ref}${s.key_hint ? ` (...${s.key_hint})` : ''}`).join('\n')}</pre>
                                        {/if}
                                        {#if preview.script}
                                            <p class="pl-label">{t('launch_profiles.preview.script')}</p>
                                            <pre class="lp-code">{preview.script}</pre>
                                        {/if}
                                    {:else}
                                        <p class="lp-note">{t('launch_profiles.preview.waiting')}</p>
                                    {/if}
                                </div>
                            </section>

                            {#if usage}
                                <section class="pl-panel" data-lp-usage>
                                    <header class="pl-titlebar"><h2 class="pl-title">{t('launch_profiles.usage.title')}</h2></header>
                                    <div class="lp-preview">
                                        {#if usage.total === 0}<p class="lp-note">{t('launch_profiles.usage.none')}</p>{/if}
                                        {#each Object.entries(usage.counts).filter(([, n]) => n > 0) as [kind, n] (kind)}
                                            <p class="lp-check__line">{kind.replace(/_/g, ' ')}: {n}</p>
                                        {/each}
                                    </div>
                                </section>
                            {/if}
                        {/if}
                    </div>
                </div>
            </div>
        </div>
    </Page>
{/if}

<style>
  @layer components {
    .lp-split { display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--pl-gutter, 16px); align-items: start; }
    @container oc-pane (min-width: 820px) { .lp-split { grid-template-columns: 360px minmax(0, 1fr); } }
    .lp-split.lp-split--solo { grid-template-columns: minmax(0, 1fr); }
    .lp-detail.lp-detail--none { display: none; }
    .lp-detail { display: flex; flex-direction: column; gap: var(--pl-gutter, 16px); min-width: 0; }
    .lp-rows { list-style: none; margin: 0; padding: 0; }
    .lp-item { display: flex; align-items: center; gap: 10px; width: 100%; min-width: 0; min-height: 40px; padding: 4px 12px; border: 0; border-bottom: 1px solid var(--pl-line-quiet); background: transparent; color: var(--pl-text); font: inherit; text-align: left; cursor: pointer; --_bd: var(--pl-line-quiet); }
    .lp-item:hover { background: var(--pl-hover); }
    .lp-item--on { background: var(--pl-raised); box-shadow: inset 2px 0 0 0 var(--pl-accent); }
    .lp-item__mark { display: inline-flex; flex: none; width: 24px; height: 24px; line-height: 0; color: var(--pl-muted); }
    .lp-item__main { display: flex; flex-direction: column; gap: 2px; min-width: 0; flex: 1 1 auto; }
    .lp-item__label { display: flex; align-items: center; gap: 8px; min-width: 0; font-size: 12px; font-weight: 600; }
    .lp-item__sub { display: flex; align-items: center; gap: 8px; min-width: 0; }
    .lp-item__name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .lp-item__facts { color: var(--pl-dim); font-family: var(--pl-mono); font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .lp-badge { flex: none; padding: 1px 6px; border: 1px solid var(--pl-line-panel); border-radius: 2px; color: var(--pl-muted); font-size: var(--oc-fs-micro, 10px); letter-spacing: var(--oc-tracking-label, 0.6px); text-transform: uppercase; white-space: nowrap; }
    .lp-badge--default { color: var(--pl-text); }
    .lp-badge--warn { border-color: var(--pl-warn); color: var(--pl-warn); }
    .lp-head { flex-wrap: wrap; padding-top: 4px; padding-bottom: 4px; }
    .lp-tools { display: flex; flex-wrap: wrap; gap: 6px; margin-left: auto; padding: 4px 0; }
    .lp-danger { border-color: var(--pl-high); color: var(--pl-high); --_bd: var(--pl-high); }
    .lp-templates { padding-bottom: 10px; }
    .lp-templates__head { margin: 10px 12px 6px; }
    .lp-templates__list { display: flex; flex-wrap: wrap; gap: 8px; padding: 0 12px; }
    .lp-empty, .lp-note { margin: 0; padding: 12px; color: var(--pl-dim); font-size: 12px; }
    .lp-error { margin: 0; padding: 6px 8px; border-left: 2px solid var(--pl-high); background: var(--pl-panel); color: var(--pl-text); font-size: 12px; overflow-wrap: anywhere; }
    .lp-refusal { margin: 12px; padding: 8px; border-left: 2px solid var(--pl-high); background: var(--pl-ground); font-size: 12px; }
    .lp-refusal__text { margin: 0 0 6px; overflow-wrap: anywhere; }
    .lp-refusal__count { margin: 0; font-family: var(--pl-mono); font-size: 11px; color: var(--pl-muted); }
    .lp-row { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; align-items: center; }
    .lp-select { min-width: 0; min-height: 32px; padding: 6px 8px; border: 1px solid var(--pl-line-panel); border-radius: var(--pl-radius-sm); background: var(--pl-ground); color: var(--pl-text); font-size: 12px; font-family: inherit; }
    .lp-result { margin: 12px; padding: 8px; border-left: 2px solid var(--pl-focus); background: var(--pl-ground); }
    .lp-check__line { margin: 4px 0 0; font-family: var(--pl-mono); font-size: 11px; color: var(--pl-text); overflow-wrap: anywhere; white-space: pre-wrap; }
    .lp-preview { padding: 10px 12px; display: flex; flex-direction: column; gap: 6px; min-width: 0; }
    .lp-code { max-height: 40vh; overflow: auto; margin: 0; padding: 8px; border: 1px solid var(--pl-line); border-radius: 2px; background: var(--pl-ground); color: var(--pl-text); font-family: var(--pl-mono); font-size: 11px; line-height: 1.45; white-space: pre-wrap; overflow-wrap: anywhere; }
  }
</style>
