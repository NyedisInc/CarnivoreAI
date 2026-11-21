import { authFetch } from '../../opscenter/api/auth.svelte';

export interface AllowProject {
  uid: string;
  name: string;
  company_uid: string | null;
}

export interface AllowCompany {
  uid: string;
  name: string;
}

export interface AllowChoices {
  projects: AllowProject[];
  companies: AllowCompany[];
}

export interface AllowApi {
  get(): Promise<AllowChoices>;
}

export const allowApi: AllowApi = {
  get: () => authFetch<AllowChoices>('/pack/allow-choices', { method: 'GET' }),
};
