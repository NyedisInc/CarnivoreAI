
import { authFetch } from '../../opscenter/api/auth.svelte';
import { resource, type Resource } from '../../opscenter/api/poll.svelte';
import { t } from '../i18n/index.svelte';

export interface ConsentOffer {
  key: string;
  sender: string;
  sender_label: string;
  account_key: string;
  label: string;
  accepted: boolean;
  pending: boolean;
}

export interface ConsentView {
  mode: 'all' | 'list' | 'none' | null;
  answered: boolean;
  may_receive_credentials: boolean;
  accepted: string[];
  offers: ConsentOffer[];
  pending: string[];
}

export interface ConsentAnswer {
  mode: 'all' | 'list' | 'none';
  accounts?: string[];
}

export const RELAY_CONSENT_POLL_MS = 15000;

export const relayConsent: Resource<ConsentView> = resource<ConsentView>(
  () => authFetch<ConsentView>('/pack/relay-consent'),
  { intervalMs: RELAY_CONSENT_POLL_MS, name: 'pack-relay-consent', topics: ['pack_relay_offer'] },
);

export function offerLabel(offer: ConsentOffer): string {
  return t('pack.consent.offer', { account: offer.label || offer.account_key, sender: offer.sender_label || offer.sender.slice(0, 8) });
}

export async function answerConsent(answer: ConsentAnswer): Promise<string> {
  try {
    await authFetch('/pack/relay-consent', { method: 'PUT', body: JSON.stringify(answer) });
  } catch (error) {
    return error instanceof Error && error.message ? error.message : t('pack.consent.error');
  }
  await relayConsent.refresh(true);
  return '';
}

/* nothing at all */
export function consentBody(ticked: readonly string[], all: boolean, keep: readonly string[] = []): ConsentAnswer {
  if (all) return { mode: 'all' };
  const accounts = [...new Set([...keep, ...ticked])];
  return accounts.length ? { mode: 'list', accounts } : { mode: 'none' };
}
