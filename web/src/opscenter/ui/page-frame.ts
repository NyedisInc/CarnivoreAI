
export const PAGE_FRAMES = ['column', 'nav', 'canvas'] as const;

export type PageFrame = (typeof PAGE_FRAMES)[number];
