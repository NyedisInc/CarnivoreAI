import { setCollapsedMany, viewCollapsed } from '../drawer/store';

export const companyFoldKey = (id: number): string => `c:${id}`;

export const ARCHIVED_FOLD_KEY = 'p:archived';

const OPEN = ':open';

export const projectFoldKey = (id: number | null | undefined): string | null => (typeof id === 'number' ? `p:${id}` : null);

export function storedFold(key: string): boolean | null {
    const list = viewCollapsed();
    if (list.includes(key)) return true;
    return list.includes(key + OPEN) ? false : null;
}

export function storeFolds(choices: ReadonlyArray<readonly [string, boolean]>): void {
    const add: string[] = [];
    const remove: string[] = [];
    for (const [key, folded] of choices) {
        if (key.startsWith('c:')) {
            (folded ? add : remove).push(key);
            continue;
        }
        add.push(folded ? key : key + OPEN);
        remove.push(folded ? key + OPEN : key);
    }
    setCollapsedMany(add, remove);
}
