
export function catalogMediaUrl(sha: string): Promise<string | null> {
    return Promise.resolve(`v1/media/${encodeURIComponent(sha)}.webp`);
}
