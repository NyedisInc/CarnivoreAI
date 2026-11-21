import { authFetch } from '../../opscenter/api/auth.svelte';

export type JobSide = 'caller' | 'host';

export interface JobView {
  id: string;
  side: JobSide;
  state: string;
  body: 'command' | 'agent' | string;
  project_uid: string;
  project_name: string | null;
  folder: string | null;
  command: string | null;
  kind: string | null;
  task_head: string | null;
  agent_type: string | null;
  computer: string | null;
  reason: string | null;
  exit_code: number | null;
  output_tail: string | null;
  applied: string[];
  deleted: string[];
  clashes: string[];
  ref: string | null;
  error_code: string | null;
  error_detail: string | null;
  question: string | null;
  question_kind: string | null;
  result_text: string | null;
  account_label: string | null;
  usage: Record<string, unknown> | null;
  created_at: number;
  started_at: number | null;
  ended_at: number | null;
  caller_session: string | null;
  worker_session_uuid: string | null;
  peer_install_id: string | null;
  worker_listing_uuid: string | null;
}

export interface JobsPage {
  jobs: JobView[];
  next_before: string | null;
}

export interface JobsQuery {
  live?: boolean;
  limit?: number;
  before?: string | null;
  caller?: string | null;
}

export interface JobsApi {
  list(query: JobsQuery): Promise<JobsPage>;
  stop(id: string): Promise<unknown>;
}

export const jobsApi: JobsApi = {
  list: (query) => {
    const params = new URLSearchParams();
    if (query.live) params.set('live', 'true');
    if (query.limit) params.set('limit', String(query.limit));
    if (query.before) params.set('before', query.before);
    if (query.caller) params.set('caller', query.caller);
    const text = params.toString();
    return authFetch<JobsPage>(`/pack/jobs${text ? `?${text}` : ''}`, { method: 'GET' });
  },
  stop: (id) => authFetch<unknown>(`/pack/jobs/${encodeURIComponent(id)}/stop`, { method: 'POST' }),
};
