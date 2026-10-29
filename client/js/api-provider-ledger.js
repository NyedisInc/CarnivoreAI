
console.log('[API Api Provider Ledger Module] Loading...');

if (typeof API !== 'function') {
    throw new Error(
        'api-provider-ledger.js loaded before api.js - class API is not defined. '
        + 'Fix the script order in client/index.html.'
    );
}

Object.assign(API.prototype, {
    async getProviderLedger() {
        return await this.call('/provider-ledger');
    },

    async listProviderAccounts() {
        return await this.call('/provider-ledger/accounts');
    },

    async saveProviderAccount(id, account) {
        return await this.call(`/provider-ledger/accounts/${encodeURIComponent(id)}`, {
            method: 'PUT',
            body: account,
            expectedStatuses: [400, 409, 422]
        });
    },

    async loginProviderAccount(id) {
        return await this.call(
            `/provider-ledger/accounts/${encodeURIComponent(id)}/login`,
            { method: 'POST', expectedStatuses: [404, 409] }
        );
    },

    async deleteProviderAccount(id) {
        return await this.call(`/provider-ledger/accounts/${encodeURIComponent(id)}`, {
            method: 'DELETE',
            expectedStatuses: [404]
        });
    },
});
