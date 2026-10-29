import { blueprintError, blueprintFromLayout } from './api';

async function fromLayout(layoutUuid: string, name?: string): Promise<{ ok: true; name: string } | { ok: false; reason: string }> {
    try {
        const saved = await blueprintFromLayout(layoutUuid, name);
        return { ok: true, name: saved.name };
    } catch (error) {
        return { ok: false, reason: blueprintError(error).detail };
    }
}

export const blueprintsLegacyBridge = {
    fromLayout,
    enabled: (): boolean => true,
};
