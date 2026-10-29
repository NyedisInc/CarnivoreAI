import { authFetch } from '../../opscenter/api/auth.svelte';

export interface Company {
  id: number;
  name: string;
  project_count: number;
  has_image?: boolean;
  image_rev?: string | null;
  hue?: number | null;
  parent_id?: number | null;
  hq_project_id?: number | null;
}

export interface ProjectCompany {
  id: number | null;
  name: string;
  company_id: number | null;
  company_name: string | null;
}

export interface DeleteCompanyResult {
  deleted: boolean;
  orphaned: number;
}

export function listCompanies(): Promise<Company[]> {
  return authFetch<{ companies: Company[] }>('/companies').then((body) => body.companies);
}

export function createCompany(name: string): Promise<Company> {
  return authFetch<Company>('/companies', { method: 'POST', body: JSON.stringify({ name }) });
}

export function renameCompany(id: number, name: string): Promise<Company> {
  return authFetch<Company>(`/companies/${id}`, { method: 'PATCH', body: JSON.stringify({ name }) });
}

export function setCompanyColor(id: number, color: string | null): Promise<Company> {
  return authFetch<Company>(`/companies/${id}`, { method: 'PATCH', body: JSON.stringify({ color }) });
}

export function deleteCompany(id: number): Promise<DeleteCompanyResult> {
  return authFetch<DeleteCompanyResult>(`/companies/${id}`, { method: 'DELETE' });
}

export function setProjectCompany(projectName: string, companyId: number | null): Promise<ProjectCompany> {
  return authFetch<ProjectCompany>(`/projects/${encodeURIComponent(projectName)}/company`, {
    method: 'PUT',
    body: JSON.stringify({ company_id: companyId }),
  });
}

export function unassignProjectCompany(projectName: string): Promise<ProjectCompany> {
  return setProjectCompany(projectName, null);
}

export interface ImageResult {
  has_image: boolean;
  image_rev?: string | null;
}

function putImage(path: string, file: Blob): Promise<ImageResult> {
  const form = new FormData();
  form.append('file', file);
  return authFetch<ImageResult>(path, { method: 'PUT', body: form });
}

export function uploadCompanyImage(id: number, file: Blob): Promise<ImageResult> {
  return putImage(`/companies/${id}/image`, file);
}

export function regenerateCompanyImage(id: number): Promise<unknown> {
  return authFetch<unknown>(`/companies/${id}/image/regenerate`, { method: 'POST' });
}

export function regenerateProjectImage(projectName: string): Promise<unknown> {
  return authFetch<unknown>(`/projects/${encodeURIComponent(projectName)}/image/regenerate`, { method: 'POST' });
}

export function removeCompanyImage(id: number): Promise<ImageResult> {
  return authFetch<ImageResult>(`/companies/${id}/image`, { method: 'DELETE' });
}

export function companyImageUrl(c: Pick<Company, 'id' | 'has_image' | 'image_rev'>): string | null {
  return c.has_image ? `/api/v1/companies/${c.id}/image?rev=${encodeURIComponent(c.image_rev ?? '')}` : null;
}

export function uploadProjectImage(projectName: string, file: Blob): Promise<ImageResult> {
  return putImage(`/projects/${encodeURIComponent(projectName)}/image`, file);
}

export function removeProjectImage(projectName: string): Promise<ImageResult> {
  return authFetch<ImageResult>(`/projects/${encodeURIComponent(projectName)}/image`, { method: 'DELETE' });
}

export function projectImageUrl(p: { name: string; has_image?: boolean; image_rev?: string | null }): string | null {
  return p.has_image
    ? `/api/v1/projects/${encodeURIComponent(p.name)}/image?rev=${encodeURIComponent(p.image_rev ?? '')}`
    : null;
}
