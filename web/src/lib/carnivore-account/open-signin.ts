import { openModal } from '../modal';
import { cancelPendingAccount, registerSignInOpener, settleSignIn, type SignInRequest } from './funnel';
import SignInModal from './SignInModal.svelte';

export async function openSignInModal(request: SignInRequest): Promise<void> {
    let result: 'signed_in' | null | undefined;
    try {
        result = await openModal<'signed_in', Record<string, unknown>>(
            SignInModal as never,
            { feature: request.feature ?? '', src: request.src },
        );
    } catch (error) {
        console.warn('[account] the sign in modal failed to open', error);
        cancelPendingAccount();
        return;
    }
    if (result === 'signed_in') await settleSignIn();
    else cancelPendingAccount();
}

export function installSignInModal(): void {
    registerSignInOpener((request) => void openSignInModal(request));
}
