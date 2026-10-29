import { withoutRegisterDialog } from '../carnivore-account/refusal';
import type { PublishPreview } from '../catalog/publish';
import type { Translate } from '../sessions/types';
import { codeOf, detailOf, failureLine } from './failures';
import type { PageHost } from './host';
import type { PageStore } from './page-store.svelte';
import type { ActionName } from './types';

export type ActionResult<T> = { ok: true; value: T } | { ok: false; code: string; text: string; detail: string };

export interface ActionDeps {
    store: PageStore;
    host: PageHost;
    t: Translate;
    now?: () => Date;
}

export interface PageActions {
    check(location: string, version: string): Promise<ActionResult<PublishPreview>>;
    send(body: { location: string; version: string; digest: string }): Promise<ActionResult<{ submission_id?: string; item_id?: string }>>;
    media(location: string | null, body: { kind: string; name: string; image_base64: string; source?: 'made' | 'yours' }): Promise<ActionResult<{ submission_id?: string }>>;
    appeal(id: string, text: string, location?: string | null): Promise<ActionResult<null>>;
    withdraw(id: string, location?: string | null): Promise<ActionResult<null>>;
    register(body: { terms_version?: string; age_16_plus?: boolean; handle?: string }): Promise<ActionResult<null>>;
    refresh(): Promise<void>;
}

export function createActions({ store, host, t, now = () => new Date() }: ActionDeps): PageActions {
    async function run<T>(name: ActionName, call: () => Promise<T>, reload: () => Promise<void>): Promise<ActionResult<T>> {
        store.setActionFailure(name, null);
        let value: T;
        try {
            value = await call();
        } catch (error) {
            store.setActionFailure(name, error);
            return { ok: false, code: codeOf(error), text: failureLine(name, error, t), detail: detailOf(error) };
        }
        await reload();
        return { ok: true, value };
    }
    return {
        check: (location, version) =>
            run('check', () => host.preview({ location, version }), async () => {}).then((result) => {
                if (result.ok) {
                    const p = result.value;
                    store.checks[location] = { version, ok: p.can_send, at: now().toISOString(), summary: '', preview: p };
                    void store.loadFacts(location);
                }
                return result;
            }),
        send: (body) =>
            run('send', () => host.send(body), () => store.reloadAfterWrite(body.location)).then((result) => {
                const kept = store.facts[body.location]?.checks[0]?.digest;
                if (!result.ok && result.code === 'folder_changed') {
                    store.staleDigests[body.location] = kept ?? '';
                    store.staleAt[body.location] = now().getTime();
                }
                return result;
            }),
        media: (location, body) => run('media', () => host.sendHero(body), () => store.reloadAfterWrite(location ?? store.sel)),
        appeal: (id, text, location = null) => run('appeal', () => host.appeal(id, text).then(() => null), () => store.reloadAfterWrite(location ?? store.sel)),
        withdraw: (id, location = null) => run('withdraw', () => host.withdraw(id).then(() => null), () => store.reloadAfterWrite(location ?? store.sel)),
        register: (body) => run('register', () => withoutRegisterDialog(() => host.register(body)).then(() => null), () => store.reloadAfterRegister()),
        refresh: () => store.refresh(),
    };
}
