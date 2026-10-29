
import { authFetch } from '../../opscenter/api/auth.svelte';

export interface ComputerEntry {
  install_id: string;
  label: string;
  host_key: string | null;
  transport: 'tls' | 'ssh';
  role: 'member' | 'main' | 'peer';
  state: string;
  direction: 'both' | 'one_way';
  fid: string;
  fid_short: string;
  cert_sha256: string | null;
  joined_at: string | null;
  last_link_at: string | null;
  possible_duplicate_of: string | null;
  dial?: { state: 'linked' | 'dialing' | 'unreachable' | 'local_network_blocked' | 'refused' | 'cert_mismatch'; since: string | null } | null;
  firewall_on?: boolean;
}

export interface InviteEntry {
  id: string;
  kind: 'code' | 'ssh_add';
  code_live: boolean;
  expires_at: string | null;
  attempts_left: number;
}

export interface AddJob {
  id: string;
  target: string;
  host_key_sha256: string;
  state: string;
  step: string | null;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  computer: string | null;
}

export interface ComputersView {
  self: {
    install_id: string;
    label: string;
    fid_short: string;
    role: 'standalone' | 'main' | 'member';
    link: {
      state: string;
      port: number | null;
      join_open: boolean;
      addresses: string[];
      code_paused_until: string | null;
    };
    main: { label: string; state: string; last_link_at: string | null; reachable_note: boolean } | null;
  };
  computers: ComputerEntry[];
  invites: InviteEntry[];
  add_jobs: AddJob[];
}

export interface MintedInvite {
  id: string;
  code: string | null;
  link: string;
  expires_at: string;
  attempts_left: number;
  addresses: string[];
  fid_short: string;
}

export interface AddPreview {
  host_key_sha256: string;
  known: 'new' | 'same' | 'changed';
  reachable: boolean;
  auth_ok: boolean | null;
  posix_shell: boolean | null;
  blockers: string[];
}

export interface JoinStatus {
  state: 'idle' | 'waiting_relay' | 'finding' | 'connecting' | 'checking' | 'linking' | 'joined' | 'failed';
  error: string | null;
  main_label: string | null;
  candidates: { name: string; fid: string; fid_short: string; pack_name?: string | null; label?: string }[];
}

export interface JoinBody {
  code?: string;
  link?: string;
  candidate_fid?: string;
}

export const readComputers = (): Promise<ComputersView> => authFetch<ComputersView>('/computers');

export const mintInvite = (): Promise<MintedInvite> => authFetch<MintedInvite>('/computers/invites', { method: 'POST', body: '{}' });

export const cancelInvite = (id: string): Promise<unknown> =>
  authFetch(`/computers/invites/${encodeURIComponent(id)}`, { method: 'DELETE' });

export const removeComputer = (installId: string): Promise<{ removed: boolean; peer_told: boolean }> =>
  authFetch(`/computers/peers/${encodeURIComponent(installId)}`, { method: 'DELETE' });

export const putDirection = (installId: string, direction: 'both' | 'one_way'): Promise<ComputerEntry> =>
  authFetch<ComputerEntry>(`/computers/peers/${encodeURIComponent(installId)}/direction`, {
    method: 'PUT',
    body: JSON.stringify({ direction }),
  });

export const previewAdd = (sshTarget: string, sshPort: number | null): Promise<AddPreview> =>
  authFetch<AddPreview>('/computers/add/preview', {
    method: 'POST',
    body: JSON.stringify({ ssh_target: sshTarget, ...(sshPort !== null ? { ssh_port: sshPort } : {}) }),
  });

export const startAdd = (sshTarget: string, sshPort: number | null, hostKey: string): Promise<{ job_id: string }> =>
  authFetch<{ job_id: string }>('/computers/add', {
    method: 'POST',
    body: JSON.stringify({ ssh_target: sshTarget, host_key_sha256: hostKey, ...(sshPort !== null ? { ssh_port: sshPort } : {}) }),
  });

export const startJoin = (body: JoinBody): Promise<JoinStatus> =>
  authFetch<JoinStatus>('/computers/join', { method: 'POST', body: JSON.stringify(body) });

export const startLook = (): Promise<JoinStatus> => authFetch<JoinStatus>('/computers/join/look', { method: 'POST', body: '{}' });

export const readJoin = (): Promise<JoinStatus> => authFetch<JoinStatus>('/computers/join');

export const leavePack = (): Promise<{ left: boolean; main_told: boolean }> =>
  authFetch('/computers/leave', { method: 'POST', body: '{}' });
