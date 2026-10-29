import type { Translate } from '../sessions/types';
import type { HistoryApi } from './history-api';
import { confirmText, failedChecks, onlyNeedsLocalOnly, type PackAnswer } from './pack-model';

export interface PackOutcome {
    readonly started: boolean;
    readonly notice: string;
}

export async function runPackFlow(kind: 'pack' | 'unpack', name: string, api: HistoryApi, t: Translate): Promise<PackOutcome> {
    const pack = api.pack;
    if (!pack || !api.confirm) return { started: false, notice: t('projects.page.pack.unavailable') };
    try {
        let accept = false;
        let plan: PackAnswer = await pack.plan(kind, name, false);
        if (!plan.ok && kind === 'pack' && onlyNeedsLocalOnly(plan)) {
            const sure = await api.confirm({
                title: t('projects.page.pack.only_copy_title'),
                message: t('projects.page.pack.only_copy', { repos: plan.local_only.join('; ') }),
                detail: t('projects.page.pack.only_copy_detail'),
                confirmLabel: t('projects.page.pack.confirm_anyway'),
                cancelLabel: t('projects.page.rename.cancel'),
            });
            if (!sure) return { started: false, notice: '' };
            accept = true;
            plan = await pack.plan(kind, name, true);
        }
        if (!plan.ok) return { started: false, notice: t('projects.page.pack.refused', { reasons: failedChecks(plan) }) };
        const text = confirmText(name, plan, t);
        const yes = await api.confirm({
            title: t(`projects.page.${kind}.title`),
            message: text.message,
            detail: text.detail,
            confirmLabel: t(`projects.page.${kind}.confirm`),
            cancelLabel: t('projects.page.rename.cancel'),
        });
        if (!yes) return { started: false, notice: '' };
        await pack.apply(kind, name, plan.fingerprint, accept);
        return { started: true, notice: t(`projects.page.${kind}.started`, { name }) };
    } catch (error) {
        return { started: false, notice: error instanceof Error ? error.message : String(error) };
    }
}
