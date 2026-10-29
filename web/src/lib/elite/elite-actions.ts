import { ELITE_KEYS as K } from '../../../../client/js/labels/warez-elite.js';
import { SKILL_KEYS, refusalMessage } from '../../../../client/js/labels/skill.js';
import { latestVersion, type CardView } from '../catalog/card';
import type { CatalogHost } from '../catalog/catalog';
import InstallSheet from '../catalog/InstallSheet.svelte';
import { tryItem } from '../catalog/try-flow';
import type { LedgerOutcome } from '../catalog/update-flow';
import { runUpdate } from '../catalog/update-flow';
import { ledgerFailure } from '../catalog/installed-actions';
import type { InstalledItem, SheetOutcome } from '../catalog/types';
import { openModal, openModalCount } from '../modal';
import type { Translate } from '../sessions/types';
import { batchTake, taggedRows } from './batch';
import type { Board } from './board.svelte';
import type { EliteData } from './elite-data.svelte';

export interface ActionDeps {
    host: CatalogHost;
    data: EliteData;
    board: Board;
    t: Translate;
}

export interface EliteActions {
    add(one?: string | null): Promise<void>;
    batch(mode: 'd' | 'u'): Promise<void>;
    clear(): void;
    tryFile(one?: string | null): Promise<void>;
}

export function outcomeText(outcome: LedgerOutcome, t: Translate): string {
    if (outcome.kind === 'refused') return refusalMessage(outcome.code, t);
    if (outcome.kind === 'unsupported') return t(SKILL_KEYS.refusedUnsupported);
    if (outcome.kind === 'stale') return t(SKILL_KEYS.updateStale);
    return refusalMessage('', t);
}

export function createActions({ host, data, board, t }: ActionDeps): EliteActions {
    let running = false;
    const say = (text: string, cmd: string): void => board.say(text, cmd);
    const cardOf = (id: string): CardView | undefined => data.cards.find((c) => c.id === id);

    async function sheet(card: CardView): Promise<{ result: 'installed' | 'refused' | 'cancelled'; code?: string | null }> {
        const id = card.id;
        data.catalog.send(id, { kind: 'verify' });
        const answer = (await openModal(InstallSheet as never, { card, host, t, prefill: null } as never)) as SheetOutcome | null;
        if (answer && answer.outcome === 'installed') {
            data.catalog.send(id, { kind: 'install' });
            data.catalog.send(id, { kind: 'installed' });
            data.catalog.setInstalled(id, answer.row);
            return { result: 'installed' };
        }
        if (answer && answer.outcome === 'refused') {
            data.catalog.send(id, { kind: 'refused', code: answer.code ?? '' });
            return { result: 'refused', code: answer.code };
        }
        data.catalog.send(id, { kind: 'dismiss' });
        return { result: 'cancelled' };
    }

    async function update(card: CardView, copy: InstalledItem): Promise<{ result: 'installed' | 'refused' | 'cancelled'; code?: string | null; text?: string }> {
        const id = card.id ?? '';
        const outcome = await runUpdate({ host, t, name: card.headline ?? id, card, installed: copy });
        if (outcome.kind === 'updated') {
            data.catalog.setInstalled(id, outcome.row);
            if (outcome.row.update_available !== true) data.catalog.send(id, { kind: 'installed' });
            return { result: 'installed' };
        }
        if (outcome.kind === 'cancelled') return { result: 'cancelled' };
        if (outcome.outcome.kind === 'stale' && outcome.outcome.row) data.catalog.setInstalled(id, outcome.outcome.row);
        return { result: 'refused', text: outcomeText(outcome.outcome, t) };
    }

    async function run(ids: string[], cmd: string): Promise<void> {
        const list = ids.map(cardOf).filter((c): c is CardView => !!c);
        if (!list.length) {
            say(t(K.echoNoFile), cmd);
            return;
        }
        const name = (c: CardView): string => c.headline ?? c.id ?? '';
        if (data.offline) {
            say(t(K.echoAddOffline, { name: name(list[0]!) }), cmd);
            return;
        }
        if (running || openModalCount() > 0) return;
        running = true;
        try {
            for (let i = 0; i < list.length; i++) {
                const card = list[i]!;
                if (list.length > 1) say(t(K.echoBatch, { n: i + 1, total: list.length, name: name(card) }), cmd);
                const copy = (data.installed[card.id ?? ''] ?? []).find((r) => r.update_available === true) ?? null;
                const out = copy ? await update(card, copy) : await sheet(card);
                if (out.result === 'installed') say(t(copy ? K.echoUpdated : K.echoInstalled, { name: name(card) }), cmd);
                else if (out.result === 'refused') {
                    const reason = 'text' in out && out.text ? out.text : refusalMessage(out.code ?? '', t);
                    say(t(K.echoRefused, { name: name(card), reason }), cmd);
                } else {
                    say(list.length > 1 ? t(K.echoCancelledRest, { name: name(card), n: list.length }) : t(K.echoCancelled, { name: name(card) }), cmd);
                    break;
                }
            }
        } finally {
            running = false;
            board.untag(ids);
        }
    }

    return {
        async add(one) {
            const tagged = [...board.tagged];
            const target = one && !tagged.length ? [one] : tagged.length ? tagged : board.sel ? [board.sel] : [];
            await run(target, '+');
        },
        async batch(mode) {
            const cmd = mode === 'd' ? 'D' : 'U';
            const rows = taggedRows(board.tagged, data.listing, data.cards, data.installed);
            if (!rows.length) {
                say(t(K.echoNothingTagged), cmd);
                return;
            }
            const go = batchTake(mode, rows);
            if (!go.length) {
                say(t(mode === 'u' ? K.echoNoUpdates : K.echoNothingDl), cmd);
                return;
            }
            await run(go.map((r) => r.id), cmd);
        },
        clear() {
            const n = board.clearTags();
            say(t(n ? K.echoCleared : K.echoNoneTagged), 'C');
        },
        async tryFile(one) {
            const id = one ?? board.sel;
            const card = id ? cardOf(id) : undefined;
            if (!card) {
                say(t(K.echoNoFile), '=');
                return;
            }
            const name = card.headline ?? card.id ?? '';
            if (card.untrusted) {
                say(t(K.echoTryNa, { name }), '=');
                return;
            }
            if (running || openModalCount() > 0) return;
            running = true;
            try {
                const item = data.listing.find((i) => i.id === card.id) ?? null;
                const result = await tryItem({ host, t, card, name, files: latestVersion(item)?.files ?? null });
                if (result.kind === 'failed') say(t(K.echoRefused, { name, reason: outcomeText(ledgerFailure(result.error), t) }), '=');
            } finally {
                running = false;
            }
        },
    };
}
