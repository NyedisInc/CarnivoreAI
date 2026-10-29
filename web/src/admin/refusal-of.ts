import { ApiRefusal, type Refusal } from './admin.js';

export function refusalOf(error: unknown): Refusal {
    return error instanceof ApiRefusal ? error.refusal : { status: 0, code: 'offline', params: {} };
}
