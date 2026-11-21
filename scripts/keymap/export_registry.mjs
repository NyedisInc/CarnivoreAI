import { writeFileSync } from 'node:fs';
import { ACTIONS } from '../../client/js/keymap/actions.js';

export const slim = (a) => ({ id: a.id, labelKey: a.labelKey, category: a.category, scope: a.scope, mayShare: a.mayShare, rebindable: a.rebindable, keys: a.keys });

if (process.argv[1] && import.meta.url === new URL(`file://${process.argv[1]}`).href) {
    const out = new URL('../../src/core/keymap/registry.json', import.meta.url);
    writeFileSync(out, `[\n${ACTIONS.map((a) => JSON.stringify(slim(a))).join(',\n')}\n]\n`);
}
