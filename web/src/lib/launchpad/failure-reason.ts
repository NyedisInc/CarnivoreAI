import type { Translate } from '../sessions/types';

export function reasonOf(error: unknown, t: Translate): string {
    const message = error instanceof Error ? error.message : String(error ?? '');
    return message || t('error.server_unreachable');
}
