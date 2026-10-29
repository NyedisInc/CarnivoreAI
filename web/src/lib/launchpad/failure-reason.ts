import type { Translate } from '../sessions/types';
import { reasonOf as sharedReasonOf } from '../../../../client/js/labels/error-reason.js';

export function reasonOf(error: unknown, t: Translate): string {
    return sharedReasonOf(error, t);
}
