import { registerFragment } from '../../../../../client/js/i18n/catalogs.js';

export const FIXTURE_PLUGIN = 'boardfix';
export const FIXTURE_NAME = 'board fixture';
export const FIXTURE_BOARDS_LABEL = 'fixture boards';

export function registerFixturePlugin(): number {
    return registerFragment(FIXTURE_PLUGIN, {
        [`cplug.${FIXTURE_PLUGIN}.name`]: FIXTURE_NAME,
        [`cplug.${FIXTURE_PLUGIN}.data.boards`]: FIXTURE_BOARDS_LABEL,
    });
}
