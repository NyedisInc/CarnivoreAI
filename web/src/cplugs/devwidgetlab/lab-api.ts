import { ApiError, authFetch } from '../sdk';
import type { DraftRequest, DraftsState, DraftSummary } from './drafts-model';
import type { CaptureOutcome, CaptureRequest, MatrixState } from './lab-model';

export interface LabStatus {
  available: boolean;
  reason: string;
  captures_dir: string;
}

export function labStatus(): Promise<LabStatus> {
  return authFetch<LabStatus>('/cplugs/devwidgetlab/status');
}

export function refusalText(error: ApiError): string {
  const detail = (error.payload as { detail?: { detail?: string; code?: string } } | null)?.detail;
  return detail?.detail || detail?.code || error.code || error.message;
}

export async function runCapture(request: CaptureRequest): Promise<CaptureOutcome> {
  try {
    return await authFetch<CaptureOutcome>('/cplugs/devwidgetlab/capture', { method: 'POST', body: JSON.stringify(request) });
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    return { ok: false, determined: false, failures: [refusalText(error)] };
  }
}

export function fitTableState(): Promise<MatrixState> {
  return authFetch<MatrixState>('/cplugs/devwidgetlab/fit-table');
}

export async function startMatrix(catalog: boolean, only: string | null = null): Promise<{ state: MatrixState | null; refusal: string }> {
  try {
    return { state: await authFetch<MatrixState>('/cplugs/devwidgetlab/matrix', { method: 'POST', body: JSON.stringify(only === null ? { catalog } : { catalog, only }) }), refusal: '' };
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    return { state: null, refusal: refusalText(error) };
  }
}

export const draftApi = {
  list: (): Promise<DraftsState> => authFetch<DraftsState>('/cplugs/devwidgetlab/drafts'),
  create: (request: DraftRequest): Promise<DraftSummary> => authFetch<DraftSummary>('/cplugs/devwidgetlab/drafts', { method: 'POST', body: JSON.stringify(request) }),
  build: (slug: string): Promise<DraftSummary> => authFetch<DraftSummary>(`/cplugs/devwidgetlab/drafts/${slug}/build`, { method: 'POST' }),
  ticket: (slug: string): Promise<{ path: string; expires_in: number; rebuild?: boolean }> => authFetch(`/cplugs/devwidgetlab/drafts/${slug}/ticket`, { method: 'POST' }),
  handToClaude: (slug: string): Promise<DraftSummary> => authFetch<DraftSummary>(`/cplugs/devwidgetlab/drafts/${slug}/hand-to-claude`, { method: 'POST' }),
  file: (slug: string, path: string): Promise<{ path: string; content: string }> => authFetch(`/cplugs/devwidgetlab/drafts/${slug}/file?path=${encodeURIComponent(path)}`),
  putFile: (slug: string, path: string, content: string): Promise<unknown> => authFetch(`/cplugs/devwidgetlab/drafts/${slug}/file`, { method: 'PUT', body: JSON.stringify({ path, content }) }),
  discard: (slug: string): Promise<{ discarded: string }> => authFetch(`/cplugs/devwidgetlab/drafts/${slug}`, { method: 'DELETE' }),
};
