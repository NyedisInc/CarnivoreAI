import { authFetch } from '../../opscenter/api/auth.svelte';
import { createCompany as postCompany, listCompanies, setCompanyFolder } from '../companies/api';
import type { CompanyRow, FolderTree, Verdict } from './model';

export interface NewProjectApi {
    loadCompanies(): Promise<CompanyRow[]>;
    loadTree(): Promise<FolderTree>;
    check(path: string, companyId: number | null): Promise<Verdict>;
    createCompany(name: string, parentId: number | null, folder: string | null): Promise<CompanyRow>;
}

async function makeFolder(path: string): Promise<void> {
    await authFetch('/filesystem/mkdir', { method: 'POST', body: JSON.stringify({ path }) });
}

export const liveApi: NewProjectApi = {
    loadCompanies: () => listCompanies(),
    loadTree: () => authFetch<FolderTree>('/projects/folder-tree'),
    check: (path, companyId) =>
        authFetch<Verdict>('/projects/landing-check', { method: 'POST', body: JSON.stringify({ path, company_id: companyId }) }),
    async createCompany(name, parentId, folder) {
        const company = await postCompany(name, parentId);
        if (!folder) return company;
        await makeFolder(folder);
        return setCompanyFolder(company.id, folder);
    },
};
