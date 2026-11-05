
Object.assign(API.prototype, {
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
});
