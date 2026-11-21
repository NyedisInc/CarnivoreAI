
<script lang="ts">
    import { onMount } from 'svelte';
    import { t as reactiveT } from '../i18n/index.svelte';
    import { NEW_PROJECT_KEYS, landsLine } from '../../../../client/js/labels/new-project.js';
    import { nameRefusal } from '../../../../client/js/labels/project-create.js';
    import { validateName } from '../launchpad/project-folder';
    import type { Translate } from '../sessions/types';
    import { reasonOf } from '../launchpad/failure-reason';
    import ModalShell from '../dialog-frame/ModalShell.svelte';
    import Button from '../base/Button.svelte';
    import Field from '../base/Field.svelte';
    import Select, { type SelectChoice } from '../base/Select.svelte';
    import Tree, { type TreeNode } from '../base/Tree.svelte';
    import Tag from '../base/Tag.svelte';
    import State from '../base/State.svelte';
    import LandsIn, { type LandsLine } from '../base/LandsIn.svelte';
    import NewCompanyBox from './NewCompanyBox.svelte';
    import { liveApi, type NewProjectApi } from './api';
    import {
        NEW_COMPANY, NO_PARENT, ancestorPaths, companyChoices, companyFolderFor, finalPath, isInside, owningCompany, relativeTo,
        rootPrefix, slugify, toTreeNodes, type CompanyRow, type Finding, type FolderTree, type TreeFolder, type Verdict,
    } from './model';
    import type { NewProjectChoice } from '../launchpad/modal-types';

    const CHECK_DEBOUNCE_MS = 120;

    interface Props {
        title: string;
        confirmLabel: string;
        defaultName?: string;
        api?: NewProjectApi;
        t?: Translate;
        close: (value: NewProjectChoice | null) => void;
    }

    let { title, confirmLabel, defaultName = '', api = liveApi, t = reactiveT, close }: Props = $props();

    // svelte-ignore state_referenced_locally
    let name = $state(defaultName);
    let companies = $state<CompanyRow[]>([]);
    let companiesError = $state('');
    let companyValue = $state('');
    let tree = $state<FolderTree | null>(null);
    let treeError = $state('');
    let selected = $state<string | null>(null);
    let open = $state<Record<string, boolean>>({});
    let filter = $state('');
    let ncName = $state('');
    let ncParent = $state(NO_PARENT);
    let ncFolder = $state('');
    let ncError = $state('');
    let busy = $state(false);
    let verdict = $state<Verdict | null>(null);
    let checkError = $state('');
    let nameEl: HTMLInputElement | null = $state(null);
    let checkSeq = 0;

    const root = $derived(tree?.root ?? '');
    const creating = $derived(companyValue === NEW_COMPANY);
    const companyId = $derived(creating || companyValue === '' ? null : Number(companyValue));
    const slug = $derived(slugify(name));
    const nameVerdict = $derived(validateName(name));
    const nameError = $derived(name.trim() ? (nameRefusal(nameVerdict, t) ?? undefined) : undefined);
    const target = $derived(selected ? finalPath(selected, name) : '');
    const nodes = $derived(toTreeNodes(tree?.nodes ?? [], root, filter));

    const companyOptions = $derived.by((): SelectChoice[] => [
        { value: '', label: t(NEW_PROJECT_KEYS.companyChoose), disabled: true },
        ...companyChoices(companies, (company) => t(NEW_PROJECT_KEYS.companyParentItself, { company })),
        { value: NEW_COMPANY, label: t(NEW_PROJECT_KEYS.companyNew) },
    ]);
    const parentOptions = $derived.by((): SelectChoice[] => [
        { value: NO_PARENT, label: t(NEW_PROJECT_KEYS.newcoParentNone) },
        ...companyChoices(companies, (company) => t(NEW_PROJECT_KEYS.companyParentItself, { company })),
    ]);

    const ncResolved = $derived.by((): string => {
        const parent = companies.find((c) => String(c.id) === ncParent);
        return companyFolderFor(ncFolder, parent?.folder ?? null, root, ncName);
    });
    const ncHelp = $derived(
        ncResolved
            ? t(NEW_PROJECT_KEYS.newcoFolderHelp, { folder: `${relativeTo(ncResolved, root)}/`, root: rootPrefix(root) })
            : t(NEW_PROJECT_KEYS.newcoFolderHelpBlank, { root: rootPrefix(root) }),
    );

    const lines = $derived.by((): LandsLine[] => {
        const found: Finding[] = [];
        if (!selected) found.push({ level: 'warn', code: 'pick_folder', params: {} });
        else if (!slug) found.push({ level: 'warn', code: 'name_missing', params: {} });
        else {
            for (const f of verdict?.findings ?? []) {
                if (creating && f.code === 'no_company') {
                    const parent = companies.find((c) => String(c.id) === ncParent);
                    found.push({ level: 'ok', code: 'new_company', params: { company: ncName.trim() || '…', parent: parent?.name ?? t(NEW_PROJECT_KEYS.newcoParentNone) } });
                } else found.push(f);
            }
            if (verdict && !verdict.findings.some((f) => f.level === 'block')) found.push({ level: 'ok', code: 'name', params: { name: name.trim() } });
        }
        const out = found.map((f) => landsLine(f, t) as LandsLine);
        if (checkError) out.push({ level: 'warn', word: t('newproject.lands.level_warn'), text: t(NEW_PROJECT_KEYS.landsFailed, { reason: checkError }) });
        return out;
    });

    const blocked = $derived(verdict?.findings.some((f) => f.level === 'block') ?? false);
    const hasCompany = $derived(companyId !== null || (creating && ncName.trim().length > 0));
    const canCreate = $derived(!busy && nameVerdict.ok && !!target && !!slug && verdict !== null && !blocked && hasCompany);

    onMount(() => {
        void loadAll();
        const timer = setTimeout(() => nameEl?.focus(), 100);
        return () => clearTimeout(timer);
    });

    async function loadAll(): Promise<void> {
        const [companyRead, treeRead] = await Promise.allSettled([api.loadCompanies(), api.loadTree()]);
        if (companyRead.status === 'fulfilled') companies = companyRead.value;
        else companiesError = reasonOf(companyRead.reason, t);
        if (treeRead.status === 'fulfilled') tree = treeRead.value;
        else treeError = reasonOf(treeRead.reason, t);
    }

    $effect(() => {
        const path = target;
        const chosen = companyId;
        if (!path) {
            verdict = null;
            return;
        }
        const mine = ++checkSeq;
        const timer = setTimeout(async () => {
            try {
                const answer = await api.check(path, chosen);
                if (mine !== checkSeq) return;
                verdict = answer;
                checkError = '';
            } catch (error) {
                if (mine !== checkSeq) return;
                verdict = null;
                checkError = reasonOf(error, t);
            }
        }, CHECK_DEBOUNCE_MS);
        return () => clearTimeout(timer);
    });

    function pickFolder(folder: string): void {
        selected = folder;
        const opened: Record<string, boolean> = {};
        for (const p of ancestorPaths(folder, root)) opened[p] = true;
        open = { ...open, ...opened };
    }

    function onCompanyChange(value: string): void {
        companyValue = value;
        ncError = '';
        if (value === NEW_COMPANY || value === '') return;
        const company = companies.find((c) => String(c.id) === value);
        if (company?.folder && isInside(company.folder, root)) {
            filter = '';
            pickFolder(company.folder);
        }
    }

    function onSelectFolder(node: TreeNode): void {
        selected = node.id;
        const owner = owningCompany(node.id, companies);
        if (owner && !creating) companyValue = String(owner.id);
    }

    async function makeCompany(): Promise<CompanyRow | null> {
        const folder = ncResolved;
        if (folder && !isInside(folder, root)) {
            ncError = t(NEW_PROJECT_KEYS.newcoOutside, { root: rootPrefix(root) });
            return null;
        }
        busy = true;
        ncError = '';
        try {
            const created = await api.createCompany(ncName.trim(), ncParent === NO_PARENT ? null : Number(ncParent), folder || null);
            companies = [...companies, created];
            tree = await api.loadTree();
            ncName = '';
            ncFolder = '';
            onCompanyChange(String(created.id));
            return created;
        } catch (error) {
            ncError = t(NEW_PROJECT_KEYS.newcoFailed, { reason: reasonOf(error, t) });
            return null;
        } finally {
            busy = false;
        }
    }

    async function submit(): Promise<void> {
        if (!canCreate) return;
        let chosen = companyId;
        if (creating) {
            chosen = (await makeCompany())?.id ?? null;
            if (chosen === null) return;
        }
        close({ name: name.trim(), folder: target, companyId: chosen as number });
    }
</script>

{#snippet folderTags(node: TreeNode)}
    {@const folder = node.data as TreeFolder}
    {#if folder.company}<Tag tone="accent">{folder.company.name}</Tag>{/if}
    {#if folder.project}<Tag tone="danger">{t(NEW_PROJECT_KEYS.treeTagProject)}</Tag>{/if}
{/snippet}

<ModalShell {title} look="titlerow" overlayClass="na-flow" width="min(48rem, 94vw)" onCancel={() => close(null)}>
    <div class="new-project-form">
        <Field label={t(NEW_PROJECT_KEYS.nameLabel)} id="new-project-name" placeholder={t(NEW_PROJECT_KEYS.namePlaceholder)}
            autocomplete="off" error={nameError} bind:value={name} bind:element={nameEl} />
        <Select label={t(NEW_PROJECT_KEYS.companyLabel)} id="new-project-company" value={companyValue} options={companyOptions}
            error={companiesError ? t(NEW_PROJECT_KEYS.companyFailed, { reason: companiesError }) : undefined}
            onchange={(event) => onCompanyChange((event.currentTarget as HTMLSelectElement).value)} />
        {#if creating}
            <NewCompanyBox bind:name={ncName} bind:parent={ncParent} bind:folder={ncFolder} parentChoices={parentOptions}
                help={ncHelp} error={ncError} {busy} canCreate={ncName.trim().length > 0}
                oncreate={() => void makeCompany()} oncancel={() => onCompanyChange('')} {t} />
        {/if}
        <Field label={t(NEW_PROJECT_KEYS.findLabel)} id="new-project-find" placeholder={t(NEW_PROJECT_KEYS.findPlaceholder)}
            autocomplete="off" bind:value={filter} />
        <div class="new-project-tree" data-new-project-tree>
            {#if treeError}
                <State kind="error" title={t(NEW_PROJECT_KEYS.treeFailed, { reason: treeError })} />
            {:else if !tree}
                <State kind="loading" title={t(NEW_PROJECT_KEYS.treeLoading)} />
            {:else if nodes.length === 0}
                <State title={t(NEW_PROJECT_KEYS.treeEmpty, { root: rootPrefix(root) })} />
            {:else}
                <Tree {nodes} label={t(NEW_PROJECT_KEYS.treeLabel, { root: rootPrefix(root) })} bind:open {selected}
                    forceOpen={filter.trim().length > 0} defaultOpen={() => false} showCount={false} branchMeta={folderTags}
                    onSelect={onSelectFolder}>
                    {#snippet leaf(node)}
                        <span class="oc-tree__label">{node.label}</span>
                        <span class="oc-tree__tags">{@render folderTags(node)}</span>
                    {/snippet}
                </Tree>
            {/if}
        </div>
        {#if tree?.truncated}<State kind="warn" inline title={t(NEW_PROJECT_KEYS.treeTruncated)} />{/if}
        <div>
            <div class="modal-label">{t(NEW_PROJECT_KEYS.pathLabel)}</div>
            <div class="folder-picker-path" data-new-project-path>
                {#if selected}{rootPrefix(root)}{relativeTo(selected, root)}/{slug || '…'}{:else}{t(NEW_PROJECT_KEYS.pathNone)}{/if}
            </div>
        </div>
        <LandsIn label={t(NEW_PROJECT_KEYS.landsLabel)} {lines} />
    </div>
    {#snippet footer()}
        <Button id="new-project-cancel" onclick={() => close(null)}>{t(NEW_PROJECT_KEYS.cancel)}</Button>
        <Button variant="confirm" id="new-project-confirm" disabled={!canCreate} onclick={() => void submit()}>{confirmLabel}</Button>
    {/snippet}
</ModalShell>

<style>
    @layer components {
        .new-project-form {
            display: flex;
            flex-direction: column;
            gap: var(--oc-space-4);
            min-width: 0;
        }

        .new-project-tree {
            min-width: 0;
            max-height: 18rem;
            overflow: auto;
            border: var(--oc-border) solid var(--oc-line-hairline);
            background: var(--oc-ground-field);
        }
    }
</style>
