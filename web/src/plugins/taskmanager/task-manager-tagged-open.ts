
export const TAGGED_OPEN: unique symbol = Symbol('task-manager-tagged-open');

export type TaggedOpener = (sessionUuid: string) => void;
