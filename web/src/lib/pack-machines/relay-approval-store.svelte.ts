
import { authFetch } from '../../opscenter/api/auth.svelte';
import { resource, type Resource } from '../../opscenter/api/poll.svelte';
import { t } from '../i18n/index.svelte';

export interface ApprovalComputer {
  install_id: string;
  label: string;
  answer: 'yes' | 'no' | null;
  pending: boolean;
  decided_by?: 'here' | 'alpha';
  alpha_yes?: boolean;
}

export interface ApprovalView {
  computers: ApprovalComputer[];
  covers_pack?: boolean;
}

export const RELAY_APPROVAL_POLL_MS = 15000;

export const relayApproval: Resource<ApprovalView> = resource<ApprovalView>(
  () => authFetch<ApprovalView>('/pack/relay-approval'),
  { intervalMs: RELAY_APPROVAL_POLL_MS, name: 'pack-relay-approval', topics: ['pack_relay_offer'] },
);

export async function answerApproval(installId: string, answer: 'yes' | 'no'): Promise<string> {
  try {
    await authFetch(`/pack/relay-approval/${encodeURIComponent(installId)}`, { method: 'PUT', body: JSON.stringify({ answer }) });
  } catch (error) {
    return error instanceof Error && error.message ? error.message : t('pack.approval.error');
  }
  await relayApproval.refresh(true);
  return '';
}
