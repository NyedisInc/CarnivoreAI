import { t } from '../i18n/index.svelte';
import {
    setProjectCompany, createCompany, deleteCompany, renameCompany, unassignProjectCompany,
    type Company,
} from '../companies';
import { announce, announceFailure, hg, reasonOf } from './interaction-globals';

export interface PromptOptions {
    title: string;
    label: string;
    placeholder?: string;
    defaultValue?: string;
    confirmLabel: string;
    cancelLabel: string;
}

export async function promptText(options: PromptOptions): Promise<string | null> {
    const modal = (globalThis as { TextPromptModal?: { open?: (o: PromptOptions) => Promise<string | null> } }).TextPromptModal;
    if (typeof modal?.open !== 'function') {
        announceFailure(t('sidebar.company.no_prompt'));
        return null;
    }
    return modal.open(options);
}

export type CompanyAction = 'create' | 'file' | 'unfile' | 'rename' | 'delete';

export function companyFailure(err: unknown, action: CompanyAction): string {
    if ((err as { status?: number } | null)?.status === 409) return t('sidebar.company.duplicate');
    return t(`sidebar.company.failed.${action}`, { reason: reasonOf(err) });
}

export async function newCompanyPrompt(projectName: string | null): Promise<Company | null> {
    const raw = await promptText({
        title: t('sidebar.company.new.title'),
        label: t('sidebar.company.new.label'),
        placeholder: t('sidebar.company.new.placeholder'),
        confirmLabel: t('sidebar.company.new.create'),
        cancelLabel: t('sidebar.company.cancel'),
    });
    if (raw === null) return null;
    let made: Company;
    try {
        made = await createCompany(raw.trim());
    } catch (err) {
        announceFailure(companyFailure(err, 'create'));
        return null;
    }
    if (!projectName) {
        announce(t('sidebar.company.created', { name: made.name }));
        return made;
    }
    await fileProject(projectName, made);
    return made;
}

export async function fileProject(projectName: string, company: Company): Promise<boolean> {
    try {
        await setProjectCompany(projectName, company.id);
        announce(t('sidebar.company.filed', { project: projectName, name: company.name }));
        return true;
    } catch (err) {
        announceFailure(companyFailure(err, 'file'));
        return false;
    }
}

export async function removeFromCompany(projectName: string): Promise<boolean> {
    try {
        await unassignProjectCompany(projectName);
        announce(t('sidebar.company.unfiled', { project: projectName }));
        return true;
    } catch (err) {
        announceFailure(companyFailure(err, 'unfile'));
        return false;
    }
}

export async function renameCompanyPrompt(company: Company): Promise<boolean> {
    const raw = await promptText({
        title: t('sidebar.company.rename.title'),
        label: t('sidebar.company.new.label'),
        defaultValue: company.name,
        confirmLabel: t('sidebar.company.rename.confirm'),
        cancelLabel: t('sidebar.company.cancel'),
    });
    if (raw === null || raw.trim() === company.name) return false;
    try {
        const next = await renameCompany(company.id, raw.trim());
        announce(t('sidebar.company.renamed', { name: next.name }));
        return true;
    } catch (err) {
        announceFailure(companyFailure(err, 'rename'));
        return false;
    }
}

/* nothing else is touched */
export async function deleteCompanyConfirm(company: Company): Promise<boolean> {
    const app = hg().App;
    if (!app) return false;
    const ok = await app.showConfirmModal(
        t('sidebar.company.delete.title'),
        t('sidebar.company.delete.message', { name: company.name }),
        t('sidebar.company.delete.detail'),
        t('sidebar.company.delete.confirm'),
        t('sidebar.company.cancel'),
        'danger',
    );
    if (!ok) return false;
    try {
        const res = await deleteCompany(company.id);
        announce(t('sidebar.company.deleted', { name: company.name, count: res.orphaned }));
        return true;
    } catch (err) {
        announceFailure(companyFailure(err, 'delete'));
        return false;
    }
}
