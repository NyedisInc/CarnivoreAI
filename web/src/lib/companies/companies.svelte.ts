import { resource, type Resource } from '../../opscenter/api/poll.svelte';
import { listCompanies, type Company } from './api';

export const COMPANIES_POLL_MS = 30000;

export const companiesResource: Resource<Company[]> = resource<Company[]>(() => listCompanies(), {
  intervalMs: COMPANIES_POLL_MS,
  name: 'companies',
  demo: () => [],
  topics: ['companies'],
});

export function sortedCompanies(list: readonly Company[] | null): Company[] {
  return [...(list ?? [])].sort(
    (a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }) || a.id - b.id,
  );
}

export const companies = {
  get list(): Company[] {
    return sortedCompanies(companiesResource.data);
  },
  get ready(): boolean {
    return companiesResource.data !== null;
  },
  refresh(): Promise<void> {
    return companiesResource.refresh(true);
  },
};

export function companyList(): Company[] {
  return companies.list;
}

export function companyById(id: number | null): Company | undefined {
  return id === null ? undefined : companiesResource.data?.find((c) => c.id === id);
}
