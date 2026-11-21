
import type { Translate } from '../sdk';

function said(key: string, t: Translate): string {
    const text = t(key);
    return text && text !== key ? text : '';
}

export function storeLabel(plugin: string, data: string, t: Translate, nameKey = ''): string {
    const own = said(`cplug.${plugin}.data.${data}`, t);
    if (own) return own;
    const name = said(nameKey || `cplug.${plugin}.name`, t) || plugin;
    return data ? t('cplug.crate.export.backup_folder_name', { plugin: name, data }) : name;
}

export function unitLabel(unit: string, t: Translate, nameKey = ''): string {
    const dot = unit.indexOf('.');
    return dot < 0 ? unit : storeLabel(unit.slice(0, dot), unit.slice(dot + 1), t, nameKey);
}
