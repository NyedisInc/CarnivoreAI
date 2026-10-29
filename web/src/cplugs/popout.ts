import { devwidgetlabPopout } from './devwidgetlab/popout';
import { flowPopout } from './flow/popout';
import { taskManagerPopout } from './huddle/popout';
import { reviewboardPopout } from './reviewboard/popout';
import type { CplugPopout } from './sdk';

export const POPOUT_CPLUGS: readonly CplugPopout[] = [taskManagerPopout, flowPopout, reviewboardPopout, devwidgetlabPopout];
