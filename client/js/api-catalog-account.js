
Object.assign(API.prototype, {
    async registerCatalogAccount(body) {
        return await this.call('/catalog/account/register', {
            method: 'POST', body,
            expectedStatuses: [400, 403, 409, 429, 502, 503],
        });
    },

    async getCatalogSession() {
        return await this.call('/catalog/auth/session');
    },

    async startCatalogDeviceFlow() {
        return await this.call('/catalog/auth/device/start', {
            method: 'POST', expectedStatuses: [503],
        });
    },

    async pollCatalogDeviceFlow(flowId) {
        return await this.call('/catalog/auth/device/poll', {
            method: 'POST', body: { flow_id: flowId }, expectedStatuses: [428],
        });
    },

    async startCatalogGoogleFlow() {
        return await this.call('/catalog/auth/google/start', {
            method: 'POST', expectedStatuses: [503],
        });
    },

    async pollCatalogGoogleFlow(flowId) {
        return await this.call('/catalog/auth/google/poll', {
            method: 'POST', body: { flow_id: flowId }, expectedStatuses: [428],
        });
    },

    async verifyCatalogGoogleMailboxCode(flowId, code, extra = {}) {
        return await this.call('/catalog/auth/google/mailbox/verify', {
            method: 'POST', body: { flow_id: flowId, code, ...extra },
            expectedStatuses: [400, 403, 410, 429, 503],
        });
    },

    async startCatalogEmailFlow(email) {
        return await this.call('/catalog/auth/email/start', {
            method: 'POST', body: { email },
            expectedStatuses: [400, 403, 410, 429, 503],
        });
    },

    async verifyCatalogEmailCode(flowId, code, extra = {}) {
        return await this.call('/catalog/auth/email/verify', {
            method: 'POST', body: { flow_id: flowId, code, ...extra },
            expectedStatuses: [400, 403, 409, 410, 429, 503],
        });
    },

    async startCatalogWebFlow(body) {
        return await this.call('/catalog/auth/web/start', {
            method: 'POST', body, expectedStatuses: [400, 409, 429, 503],
        });
    },

    async pollCatalogWebFlow(flowId) {
        return await this.call('/catalog/auth/web/poll', {
            method: 'POST', body: { flow_id: flowId },
            expectedStatuses: [400, 403, 410, 429, 502, 503],
        });
    },

    async signOutOfCatalog() {
        return await this.call('/catalog/auth/signout', { method: 'POST' });
    },

    async getCatalogAccountSessions() {
        return await this.call('/catalog/account/sessions', { expectedStatuses: [403, 502, 503] });
    },

    async revokeCatalogAccountSession(sid) {
        return await this.call(`/catalog/account/sessions/${encodeURIComponent(sid)}`, {
            method: 'DELETE', expectedStatuses: [400, 403, 502, 503],
        });
    },

    async revokeOtherCatalogSessions() {
        return await this.call('/catalog/account/sessions/revoke-others', {
            method: 'POST', expectedStatuses: [403, 502, 503],
        });
    },

    async deleteCatalogAccount(confirm) {
        return await this.call('/catalog/account/delete', {
            method: 'POST', body: { confirm },
            expectedStatuses: [400, 403, 404, 429, 502, 503],
        });
    },

    async changeCatalogHandle(handle) {
        return await this.call('/catalog/account/handle', {
            method: 'POST', body: { handle },
            expectedStatuses: [400, 403, 409, 429, 502, 503],
        });
    },

    async setCatalogNews(news) {
        return await this.call('/catalog/account/news', {
            method: 'POST', body: { news },
            expectedStatuses: [403, 429, 502, 503],
        });
    },

    async exportCatalogAccount() {
        return await this.call('/catalog/account/export', { expectedStatuses: [403, 413, 429, 502, 503] });
    },
});
