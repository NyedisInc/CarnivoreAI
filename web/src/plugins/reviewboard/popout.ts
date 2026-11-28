import manifest from '../../../../src/plugins/reviewboard/carnivore.toml';
import type { CplugManifest, CplugPopout } from '../sdk';
import { reviewboardTab } from './board-tab';
import { registerBoardKeys } from './public/board-keys';

export const reviewboardPopout: CplugPopout = { id: 'reviewboard', manifest: manifest as CplugManifest, tabs: [reviewboardTab], start: registerBoardKeys };
