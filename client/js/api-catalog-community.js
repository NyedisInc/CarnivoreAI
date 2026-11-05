
Object.assign(API.prototype, {

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
});
