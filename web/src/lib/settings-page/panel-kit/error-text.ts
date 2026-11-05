import { failureReason } from '../../errors/failure-reason';

export function errorText(error: unknown): string {
    return failureReason(error);
}
