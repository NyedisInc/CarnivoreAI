export type AuthState = 'unknown' | 'signed-in' | 'signed-out' | 'unreachable';

export const API_REFUSAL_EVENT = 'cloude:api-refusal';

export const auth: { state: AuthState; notice: string } = { state: 'signed-out', notice: '' };

export class ApiError extends Error {
    status = 0;
    detail: unknown = null;
}

export const decideBootState = (): AuthState => 'signed-out';
export const hasAccessToken = (): boolean => false;
export const hasRefreshToken = (): boolean => false;
export const accessToken = (): string | null => null;
export const initAuth = (): void => {};
export const refreshTokens = (): Promise<boolean> => Promise.resolve(false);
export const signOut = (): void => {};
export const signIn = (): Promise<void> => Promise.reject(new ApiError('the public catalog page has no sign in'));
export const authFetch = <T>(): Promise<T> => Promise.reject(new ApiError('the public catalog page makes no api calls'));
export const authFetchBlob = (): Promise<Blob> => Promise.reject(new ApiError('the public catalog page makes no api calls'));
