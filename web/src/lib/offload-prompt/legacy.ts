import { CANCELLED, canOfferRestore, isOffloadedAnswer, isOffloadedError, promptRestore, runWithOffloadRestore } from './offload-prompt';

export const offloadPromptForLegacy = {
    isOffloaded: (refusal: unknown): boolean => isOffloadedAnswer(refusal) || isOffloadedError(refusal),
    canRestore: canOfferRestore,
    prompt: promptRestore,
    run: runWithOffloadRestore,
    CANCELLED,
};
