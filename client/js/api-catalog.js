
console.log('[API Api Catalog Module] Loading...');

if (typeof API !== 'function') {
    throw new Error(
        'api-catalog.js loaded before api.js - class API is not defined. '
        + 'Fix the script order in client/index.html.'
    );
}

Object.assign(API.prototype, {

    async getCatalogItems() {
        return await this.call('/catalog/items');
    },

    async getCatalogItem(itemId) {
        return await this.call(`/catalog/items/${encodeURIComponent(itemId)}`);
    },

    async getCatalogContents(itemId) {
        return await this.call(`/catalog/contents/${encodeURIComponent(itemId)}`);
    },

    async refreshCatalogIndex() {
        return await this.call('/catalog/index/refresh', { method: 'POST' });
    },

    async catalogOpened() {
        return await this.call('/catalog/refresh', { method: 'POST' });
    },

    async getCatalogInstalled() {
        return await this.call('/catalog/installed');
    },

    async previewCatalogInstall(request) {
        return await this.call('/catalog/install/preview', {
            method: 'POST', body: request, expectedStatuses: [409],
        });
    },

    async installCatalogItem(request) {
        return await this.call('/catalog/install', {
            method: 'POST', body: request, expectedStatuses: [409],
        });
    },

    async uninstallCatalogItem(installId) {
        return await this.call(`/catalog/installed/${encodeURIComponent(installId)}`, {
            method: 'DELETE',
        });
    },

    async patchCatalogInstalled(installId, body) {
        return await this.call(`/catalog/installed/${encodeURIComponent(installId)}`, {
            method: 'PATCH', body, expectedStatuses: [409],
        });
    },

    async updateCatalogInstalled(installId, body) {
        return await this.call(
            `/catalog/installed/${encodeURIComponent(installId)}/update`,
            { method: 'POST', body, expectedStatuses: [409] },
        );
    },

    /* could not be read */
    async getCatalogItemRatings(itemId) {
        return await this.call(`/catalog/items/${encodeURIComponent(itemId)}/ratings`);
    },

    async putCatalogItemRating(itemId, body) {
        return await this.call(`/catalog/items/${encodeURIComponent(itemId)}/rating`, {
            method: 'PUT', body, expectedStatuses: [400, 401, 404, 429],
        });
    },

    async deleteCatalogItemRating(itemId) {
        return await this.call(`/catalog/items/${encodeURIComponent(itemId)}/rating`, {
            method: 'DELETE', expectedStatuses: [400, 401, 404],
        });
    },

    /* could not be read */
    async getCatalogItemInstalls(itemId) {
        return await this.call(`/catalog/items/${encodeURIComponent(itemId)}/installs`);
    },

    async getCatalogInstallCounts(ids) {
        return await this.call('/catalog/install-counts', { method: 'POST', body: { ids } });
    },


    async getCatalogComments(itemId, cursor) {
        const q = cursor ? `?cursor=${encodeURIComponent(cursor)}` : '';
        return await this.call(`/catalog/items/${encodeURIComponent(itemId)}/comments${q}`);
    },

    async getMyCatalogComments(itemId) {
        return await this.call(`/catalog/me/comments?item_id=${encodeURIComponent(itemId)}`, {
            expectedStatuses: [403],
        });
    },

    async postCatalogComment(itemId, body) {
        return await this.call(`/catalog/items/${encodeURIComponent(itemId)}/comments`, {
            method: 'POST', body, expectedStatuses: [400, 403, 404, 429, 502],
        });
    },

    async editCatalogComment(itemId, commentId, body) {
        return await this.call(
            `/catalog/items/${encodeURIComponent(itemId)}/comments/${encodeURIComponent(commentId)}`,
            { method: 'PUT', body, expectedStatuses: [400, 403, 404, 409, 429, 502] },
        );
    },

    async deleteCatalogComment(itemId, commentId) {
        return await this.call(
            `/catalog/items/${encodeURIComponent(itemId)}/comments/${encodeURIComponent(commentId)}`,
            { method: 'DELETE', expectedStatuses: [403, 404, 409, 502] },
        );
    },

    async reportCatalog(body) {
        return await this.call('/catalog/reports', {
            method: 'POST', body, expectedStatuses: [400, 403, 404, 429, 502],
        });
    },

    async getCatalogProfile(handle) {
        return await this.call(`/catalog/profiles/${encodeURIComponent(handle)}`, {
            expectedStatuses: [404],
        });
    },

    async setCatalogMailPreference(body) {
        return await this.call('/catalog/me/mail-preference', {
            method: 'PUT', body, expectedStatuses: [403, 429, 502],
        });
    },

    async getSkillUsage(skill) {
        return await this.call(`/skill-fires/usage?skill=${encodeURIComponent(skill)}`);
    },

    async getSkillAutopsy(skill, days = 30) {
        return await this.call(
            `/skills/${encodeURIComponent(skill)}/autopsy?days=${encodeURIComponent(days)}`,
        );
    },

    async restoreCatalogInstalled(installId, body) {
        return await this.call(
            `/catalog/installed/${encodeURIComponent(installId)}/restore`,
            { method: 'POST', body, expectedStatuses: [409] },
        );
    },

    async setCatalogInstalledFork(installId, forked) {
        return await this.call(
            `/catalog/installed/${encodeURIComponent(installId)}/fork`,
            { method: 'PUT', body: { forked } },
        );
    },

    async getPublishableSkills() {
        return await this.call('/catalog/publish/mine');
    },

    async previewPublish(body) {
        return await this.call('/catalog/publish/preview', {
            method: 'POST', body, expectedStatuses: [400, 404],
        });
    },

    async sendSubmission(body) {
        return await this.call('/catalog/submissions', {
            method: 'POST', body,
            expectedStatuses: [400, 403, 404, 409, 413, 429, 502, 503],
        });
    },

    async sendHeroImage(body) {
        return await this.call('/catalog/submissions/media', {
            method: 'POST', body,
            expectedStatuses: [400, 403, 404, 409, 413, 422, 429, 502, 503],
        });
    },

    async getMySubmissions() {
        return await this.call('/catalog/submissions/mine', { expectedStatuses: [403, 429, 502, 503] });
    },

    async getSubmissionReport(submissionId) {
        return await this.call(`/catalog/submissions/${encodeURIComponent(submissionId)}/report`, {
            expectedStatuses: [403, 404, 429, 502, 503],
        });
    },

    async getPublishAccount() {
        return await this.call('/catalog/handle', { expectedStatuses: [403, 502, 503] });
    },

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
