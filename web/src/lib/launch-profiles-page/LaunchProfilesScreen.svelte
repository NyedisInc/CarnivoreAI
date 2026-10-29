
<script lang="ts">
    import { captureOpener, restoreOpenerFocus } from '../dialog-frame/opener-focus';
    import { onMount } from 'svelte';
    import { registerPageDirty } from '../menu-page/menu-page-dirty';
    import '../ledger/ledger-chrome.css';
    import Page from '../../opscenter/ui/Page.svelte';
    import { Button, Card, Checkbox, List, ListRow, Select, State, Tag } from '../base';
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
    import { EXAMPLES, exampleForm } from './examples';
    import { hiddenCount, visibleProfiles } from './visibility';
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
    /* nothing is deleted */
    let pending = $state<'delete' | 'move' | null>(null);
    let pickingTemplate = $state(false);
    let showHidden = $state(false);

    const selected = $derived(form && !form.isNew ? (rows.find((r) => r.id === form!.id) ?? null) : null);
    const taken = $derived(new Set(rows.map((r) => r.id)));
    const shownRows = $derived(visibleProfiles(rows, { showHidden, keep: [form?.id] }));
    const hidden = $derived(hiddenCount(rows));

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
        saveError = null; notice = null; check = null; usage = null; refusal = null; moveTo = ''; pending = null; preview = null; previewError = null; previewModel = '';
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

    function useExample(id: string): void {
        const ex = EXAMPLES.find((x) => x.id === id);
        if (!ex) return;
        const next = exampleForm(ex, t(`launch_profiles.template.${ex.id}`), connections);
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
        pending = null;
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
        pending = null;
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
        <Button data-lp-import-open onclick={() => void importOne()}>{t('launch_profiles.page.import')}</Button>
        <Button variant="confirm" data-lp-new aria-expanded={pickingTemplate} onclick={() => (pickingTemplate = !pickingTemplate)}>{t('launch_profiles.page.new')}</Button>
    {/snippet}

    <Page class="pledger lp-page" title={t('launch_profiles.page.title')} count={shownRows.length > 0 ? t('launch_profiles.page.count', { count: shownRows.length }) : undefined}
        onClose={embedded ? undefined : close} closeLabel={t('launch_profiles.page.close')} actions={pageActions} {embedded}>
        <div class="oc-page__scroll">
            <div class="oc-page__main oc-page__main--stack">
                {#if failure}<State inline kind="error" title={t('launch_profiles.page.failed', { reason: failure })} data-lp-failure />{/if}
                {#if notice}<State inline kind={notice.error ? 'error' : 'empty'} title={notice.text} data-lp-notice />{/if}

                {#if pickingTemplate}
                    <Card title={t('launch_profiles.page.templates')} headingLevel={2} data-lp-templates>
                        {#snippet children()}
                            <div class="lp-templates">
                                {#each TEMPLATES as tpl (tpl.id)}
                                    <Button data-lp-template={tpl.id} onclick={() => startTemplate(tpl.id)}>{t(`launch_profiles.template.${tpl.id}`)}</Button>
                                {/each}
                            </div>
                        {/snippet}
                    </Card>
                {/if}

                <div class="lp-split" class:lp-split--solo={!form}>
                    <Card title={t('launch_profiles.list.title')} headingLevel={2} data-lp-list>
                        {#snippet children()}
                            {#if shownRows.length === 0 && !loading}<State inline title={t('launch_profiles.list.empty')} data-lp-empty />{/if}
                            {#if hidden > 0}
                                <div class="lp-hidden" data-lp-hidden>
                                    <Checkbox label={t('launch_profiles.list.show_hidden', { count: hidden })} bind:checked={showHidden} data-lp-show-hidden />
                                    <span class="lp-hint-line">{t('launch_profiles.list.show_hidden_hint')}</span>
                                </div>
                            {/if}
                            {#if shownRows.length > 0}
                                <List density="roomy" label={t('launch_profiles.page.title')}>
                                    {#snippet children()}
                                        {#each shownRows as r (r.id)}
                                            {@const mark = wrapperMark(r.icon, r.harness, LAUNCH_MARK_PX)}
                                            {@const on = form?.id === r.id && !form?.isNew}
                                            <ListRow selected={on}>
                                                {#snippet children()}
                                                    <Button variant="row" aria-current={on ? 'true' : undefined} data-lp-row={r.id} onclick={() => select(r)}>
                                                        <span class="lp-item__mark" role="img" aria-label={providerMark(r.harness).label} data-mark-source={mark.source}>{@html mark.svg}</span>
                                                        <span class="lp-item__main">
                                                            <span class="lp-item__label">
                                                                <span class="lp-item__name">{r.label}</span>
                                                                {#if r.default}<Tag data-lp-default>{t('launch_profiles.list.default')}</Tag>{/if}
                                                                {#if r.installed === false}<Tag tone="warn" data-lp-not-installed>{t('launch_profiles.list.not_installed')}</Tag>{/if}
                                                            </span>
                                                            <span class="lp-item__sub">
                                                                <span class="lp-item__facts">{facts(r)}</span>
                                                                {#if r.permissions !== 'harness_default'}<Tag tone={r.permissions === 'skip_all' ? 'warn' : 'neutral'} data-lp-perm={r.permissions}>{r.summary.permissions_badge}</Tag>{/if}
                                                            </span>
                                                        </span>
                                                    </Button>
                                                {/snippet}
                                            </ListRow>
                                        {/each}
                                    {/snippet}
                                </List>
                            {/if}
                            {#if !form && shownRows.length > 0}<State inline title={t('launch_profiles.page.pick')} data-lp-pick />{/if}
                        {/snippet}
                    </Card>

                    <div class="lp-detail" class:lp-detail--none={!form}>
                        {#if form}
                            {#snippet tools()}
                                <Button size="sm" data-lp-check onclick={() => void runCheck()}>{t('launch_profiles.action.check')}</Button>
                                <Button size="sm" data-lp-duplicate onclick={duplicate}>{t('launch_profiles.action.duplicate')}</Button>
                                {#if !selected?.default}<Button size="sm" data-lp-make-default onclick={() => void makeDefault()}>{t('launch_profiles.action.make_default')}</Button>{/if}
                                <Button size="sm" data-lp-export onclick={() => void exportOne()}>{t('launch_profiles.action.export')}</Button>
                                {#if pending === 'delete'}
                                    <Button size="sm" data-lp-delete-cancel onclick={() => (pending = null)}>{t('launch_profiles.editor.cancel')}</Button>
                                    <Button size="sm" variant="danger" data-lp-delete-confirm onclick={() => void remove()}>{t('launch_profiles.action.delete_confirm', { name: selected?.id ?? '' })}</Button>
                                {:else}
                                    <Button size="sm" variant="danger" data-lp-delete onclick={() => (pending = 'delete')}>{t('launch_profiles.action.delete')}</Button>
                                {/if}
                            {/snippet}
                            <Card title={form.isNew ? t('launch_profiles.editor.new_title') : form.label} headingLevel={2} actions={selected ? tools : undefined} data-lp-detail>
                                {#snippet children()}
                                    {#if refusal}
                                        <State kind="error" title={refusal.message} data-lp-refusal>
                                            {#snippet children()}
                                                <div class="lp-refusal">
                                                    {#each Object.entries(refusal!.counts).filter(([, n]) => n > 0) as [kind, n] (kind)}
                                                        <p class="lp-line" data-lp-count={kind}>{kind.replace(/_/g, ' ')}: {n}</p>
                                                    {/each}
                                                    {#if refusal!.code === 'in_use'}
                                                        <div class="lp-row">
                                                            <Select size="sm" aria-label={t('launch_profiles.action.move_to')} bind:value={moveTo} data-lp-move-to>
                                                                {#snippet children()}
                                                                    <option value="">{t('launch_profiles.action.move_to')}</option>
                                                                    {#each moveTargets as r (r.id)}<option value={r.id}>{r.label}</option>{/each}
                                                                {/snippet}
                                                            </Select>
                                                            {#if pending === 'move'}
                                                                <Button size="sm" data-lp-move-cancel onclick={() => (pending = null)}>{t('launch_profiles.editor.cancel')}</Button>
                                                                <Button size="sm" variant="danger" data-lp-move-confirm onclick={() => void moveThenDelete()}>{t('launch_profiles.action.move_delete_confirm', { target: moveTargets.find((r) => r.id === moveTo)?.label ?? moveTo })}</Button>
                                                            {:else}
                                                                <Button size="sm" disabled={!moveTo} data-lp-move onclick={() => (pending = 'move')}>{t('launch_profiles.action.move_delete')}</Button>
                                                            {/if}
                                                        </div>
                                                        {#if moveTargets.length === 0}<p class="lp-line">{t('launch_profiles.action.no_move_target', { harness: selected?.harness ?? '' })}</p>{/if}
                                                    {/if}
                                                </div>
                                            {/snippet}
                                        </State>
                                    {/if}

                                    {#if check}
                                        <div class="lp-result" role="status" data-lp-check-result>
                                            <p class="oc-label">{t('launch_profiles.check.title')}</p>
                                            <p class="lp-line">{t('launch_profiles.check.binary', { status: check.binary.status })}{check.binary.output ? `: ${check.binary.output}` : ''}</p>
                                            {#if check.endpoint}<p class="lp-line">{t(check.endpoint.ok ? 'launch_profiles.check.endpoint_ok' : 'launch_profiles.check.endpoint_failed', { models: check.endpoint.models, detail: check.endpoint.detail ?? '' })}</p>{/if}
                                        </div>
                                    {/if}

                                    <LaunchProfileEditor bind:form={() => form!, (v) => (form = v)} bind:previewModel {connections} {models} {busy} error={saveError} {t} onExample={useExample} onSave={() => void save()} onCancel={() => { form = null; resetDetail(); }} />
                                {/snippet}
                            </Card>

                            <Card title={t('launch_profiles.preview.title')} headingLevel={2} data-lp-preview>
                                {#snippet children()}
                                    {#if previewError}
                                        <State inline kind="error" role="status" title={previewError} data-lp-preview-error />
                                    {:else if preview}
                                        <div class="lp-preview">
                                            <p class="oc-label">{t('launch_profiles.preview.command')}</p>
                                            <pre class="lp-code" data-lp-preview-command>{preview.command}</pre>
                                            {#if preview.env_set.length}
                                                <p class="oc-label">{t('launch_profiles.preview.env')}</p>
                                                <pre class="lp-code" data-lp-preview-env>{preview.env_set.map((e) => `${e.name}=${e.value}`).join('\n')}</pre>
                                            {/if}
                                            {#if preview.env_unset.length}
                                                <p class="oc-label">{t('launch_profiles.preview.unset')}</p>
                                                <pre class="lp-code">{preview.env_unset.join('\n')}</pre>
                                            {/if}
                                            {#if preview.secrets.length}
                                                <p class="oc-label">{t('launch_profiles.preview.secrets')}</p>
                                                <pre class="lp-code" data-lp-preview-secrets>{preview.secrets.map((s) => `${s.name} <- ${s.keychain_ref}${s.key_hint ? ` (...${s.key_hint})` : ''}`).join('\n')}</pre>
                                            {/if}
                                            {#if preview.script}
                                                <p class="oc-label">{t('launch_profiles.preview.script')}</p>
                                                <pre class="lp-code">{preview.script}</pre>
                                            {/if}
                                        </div>
                                    {:else}
                                        <State inline title={t('launch_profiles.preview.waiting')} />
                                    {/if}
                                {/snippet}
                            </Card>

                            {#if usage}
                                <Card title={t('launch_profiles.usage.title')} headingLevel={2} data-lp-usage>
                                    {#snippet children()}
                                        {#if usage!.total === 0}<State inline title={t('launch_profiles.usage.none')} />{/if}
                                        {#each Object.entries(usage!.counts).filter(([, n]) => n > 0) as [kind, n] (kind)}
                                            <p class="lp-line">{kind.replace(/_/g, ' ')}: {n}</p>
                                        {/each}
                                    {/snippet}
                                </Card>
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
    .lp-split :global([data-lp-row]) { --_btn-ink: var(--pl-text); --_btn-ink-hover: var(--pl-text); flex: 1 1 auto; min-width: 0; align-items: center; gap: 10px; padding-block: 4px; }
    .lp-item__mark { display: inline-flex; flex: none; width: 24px; height: 24px; line-height: 0; color: var(--pl-muted); }
    .lp-item__main { display: flex; flex-direction: column; gap: 2px; min-width: 0; flex: 1 1 auto; }
    .lp-item__label { display: flex; align-items: center; gap: 8px; min-width: 0; font-size: 12px; font-weight: 600; }
    .lp-item__sub { display: flex; flex-wrap: wrap; align-items: center; gap: 2px 8px; min-width: 0; }
    .lp-item__name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .lp-item__facts { flex: 1 1 14ch; min-width: 0; color: var(--pl-dim); font-family: var(--pl-mono); font-size: 11px; font-weight: 400; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .lp-hidden { display: flex; flex-direction: column; gap: var(--oc-space-0-5); padding-bottom: var(--oc-space-2); }
    .lp-hint-line { color: var(--pl-dim); font-size: var(--oc-fs-hint); }
    .lp-templates { display: flex; flex-wrap: wrap; gap: 8px; }
    .lp-result { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
    .lp-result .oc-label { margin: 0; }
    .lp-refusal { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
    .lp-row { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 6px; align-items: center; }
    .lp-line { margin: 0; font-family: var(--pl-mono); font-size: 11px; color: var(--pl-text); overflow-wrap: anywhere; white-space: pre-wrap; }
    .lp-preview { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
    .lp-preview .oc-label { margin: 0; }
    .lp-code { max-height: 40vh; overflow: auto; margin: 0; padding: 8px; border: 1px solid var(--pl-line); border-radius: 2px; background: var(--pl-ground); color: var(--pl-text); font-family: var(--pl-mono); font-size: 11px; line-height: 1.45; white-space: pre-wrap; overflow-wrap: anywhere; }
  }
</style>
