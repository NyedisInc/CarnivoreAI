import { hostWindow } from '../sessions/env';
import type { Translate } from '../sessions/types';
import type { CatalogAuthSession, EmailFlowStart } from '../catalog/types';

export const TERMS_VERSION = '2026-10-01';

export const TERMS_URL = `https://carnivore.ai/terms/${TERMS_VERSION}/`;
export const PRIVACY_URL = 'https://carnivore.ai/privacy/';

export interface SignInConsent {
    terms_version: string;
    age_16_plus: true;
    news: boolean;
}

export interface WebStart {
    flow_id: string;
    url: string;
    expires_in: number;
    interval: number;
}

export type WebPoll = Partial<CatalogAuthSession> & { status?: 'pending'; interval?: number };

export interface SignInHost {
    startWeb(body: { provider: 'google' | 'github'; src: string; consent: SignInConsent }): Promise<WebStart>;
    pollWeb(flowId: string): Promise<WebPoll>;
    startEmail(email: string): Promise<EmailFlowStart>;
    verifyEmail(flowId: string, code: string, extra: { consent: SignInConsent; src: string }): Promise<CatalogAuthSession>;
    verifyMailbox(flowId: string, code: string, extra?: { src: string }): Promise<CatalogAuthSession>;
}

interface LegacyApi {
    startCatalogWebFlow: SignInHost['startWeb'];
    pollCatalogWebFlow: SignInHost['pollWeb'];
    startCatalogEmailFlow: SignInHost['startEmail'];
    verifyCatalogEmailCode: SignInHost['verifyEmail'];
    verifyCatalogGoogleMailboxCode: SignInHost['verifyMailbox'];
}

export function browserSignInHost(): SignInHost {
    const api = (): LegacyApi => (hostWindow() as unknown as { API: LegacyApi } | undefined)?.API as LegacyApi;
    return {
        startWeb: (body) => api().startCatalogWebFlow(body),
        pollWeb: (flowId) => api().pollCatalogWebFlow(flowId),
        startEmail: (email) => api().startCatalogEmailFlow(email),
        verifyEmail: (flowId, code, extra) => api().verifyCatalogEmailCode(flowId, code, extra),
        verifyMailbox: (flowId, code, extra) => api().verifyCatalogGoogleMailboxCode(flowId, code, extra),
    };
}

export function consentOf(news: boolean): SignInConsent {
    return { terms_version: TERMS_VERSION, age_16_plus: true, news };
}

export function signedInToast(who: string, t: Translate, now: number = Date.now()): Record<string, unknown> {
    return {
        id: `account:signed-in:${now}`,
        session_id: null,
        kind: 'AccountSignedIn',
        title: t('account.toast.title'),
        body: t('account.toast.signed_in', { who }),
        session_label: t('account.toast.surface'),
        local: true,
    };
}
