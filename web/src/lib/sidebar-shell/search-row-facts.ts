import { t } from '../i18n/index.svelte';
import type { SidebarRow } from './legacy';
import { modelPlan } from './row-chips';
import { asleepText } from './row-body';
import { ageLabel, epochFromIso } from './row-text';
import type { SearchRowFacts } from './row-plan';

export function searchRowFacts(row: SidebarRow): SearchRowFacts {
    const epoch = epochFromIso(row.last_work_at);
    const note = row.closed === true ? t('session.closed.label') : row.asleep ? asleepText(row) : null;
    const model = note === null ? modelPlan(row) : null;
    return {
        age: epoch === null ? '' : ageLabel(epoch),
        note,
        model,
        modelName: model ? String(row.running_model).trim().replace(/^claude-/, '') : '',
        effort: model && typeof row.running_model_effort === 'string' ? row.running_model_effort.trim() : '',
    };
}
