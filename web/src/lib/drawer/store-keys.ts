import { PAGE_SECTION_SLOT, pageSectionMeta } from './page-sections';


export const GROUP_KEYS: readonly string[] = ['pinned', 'other'];

export const GROUP_FOLD_PREFIX = 'g:';

export const PROJECT_FOLD_PREFIX = 'p:';

export const ROGUE_FOLD_KEY = 'rogue';

export const KIND_FOLD_KEYS: readonly string[] = ['terminals', 'browsers', 'files'];

export const LAYOUT_FOLD_KEY = 'layouts';

export const COMPANIES_FOLD_KEY = 'companies';

export const GROUPS_FOLD_KEY = 'groups';

export const PACK_FOLD_KEY = 'pack';

export const HOST_OFF_FOLD_PREFIX = 'host-off:';

export const OPEN_FOLD_KEY = 'open';

export const SLEEPING_FOLD_KEY = 'sleeping';

export const LAYOUT_ITEM_FOLD_PREFIX = 'layout:';

export const LEDGER_FOLD_KEYS: readonly string[] = ['ledger_hidden', 'ledger_expanded', 'ledger_glance'];

export const SPAWNED_FOLD_SUFFIX = ':agents';

export function isSpawnedFoldKey(key: unknown): boolean {
    return typeof key === 'string' && key.indexOf(PROJECT_FOLD_PREFIX) === 0 && key.endsWith(SPAWNED_FOLD_SUFFIX);
}

export const MAX_FOLDS = 1000;

const COMPANY_KEY_RE = /^c:(?:\d{1,18}|orphaned)$/;

export function isCompanyKey(key: unknown): boolean {
    return typeof key === 'string' && COMPANY_KEY_RE.test(key);
}

export function isFoldKey(key: unknown): key is string {
    if (typeof key !== 'string' || !key) return false;
    if (isCompanyKey(key)) return true;
    if (GROUP_KEYS.indexOf(key) !== -1) return true;
    if (key === ROGUE_FOLD_KEY) return true;
    if (key === LAYOUT_FOLD_KEY) return true;
    if (key === COMPANIES_FOLD_KEY) return true;
    if (key === GROUPS_FOLD_KEY) return true;
    if (key === PACK_FOLD_KEY) return true;
    if (key === OPEN_FOLD_KEY || key === SLEEPING_FOLD_KEY) return true;
    if (KIND_FOLD_KEYS.indexOf(key) !== -1) return true;
    if (key === PAGE_SECTION_SLOT || pageSectionMeta(key) !== null) return true;
    if (LEDGER_FOLD_KEYS.indexOf(key) !== -1) return true;
    if (key.indexOf(GROUP_FOLD_PREFIX) === 0 && key.length > GROUP_FOLD_PREFIX.length) return true;
    if (key.indexOf(HOST_OFF_FOLD_PREFIX) === 0 && key.length > HOST_OFF_FOLD_PREFIX.length) return true;
    if (key.indexOf(LAYOUT_ITEM_FOLD_PREFIX) === 0 && key.length > LAYOUT_ITEM_FOLD_PREFIX.length) return true;
    return key.indexOf(PROJECT_FOLD_PREFIX) === 0 && key.length > PROJECT_FOLD_PREFIX.length;
}

export function isBandOrderKey(key: unknown): boolean {
    if (key === LAYOUT_FOLD_KEY || key === COMPANIES_FOLD_KEY || key === GROUPS_FOLD_KEY || key === PACK_FOLD_KEY || isCompanyKey(key)) return false;
    if (key === OPEN_FOLD_KEY || key === SLEEPING_FOLD_KEY) return false;
    if (typeof key === 'string' && key.indexOf(LAYOUT_ITEM_FOLD_PREFIX) === 0) return false;
    if (isSpawnedFoldKey(key)) return false;
    if (typeof key === 'string' && key.indexOf(HOST_OFF_FOLD_PREFIX) === 0) return false;
    return isFoldKey(key) && GROUP_KEYS.indexOf(key) === -1;
}
