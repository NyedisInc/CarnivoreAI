/* the restore points tab */

export const megabytes = (bytes: number): string => (bytes / (1024 * 1024)).toFixed(1);

export const gigabytes = (bytes: number): string => (bytes / (1024 * 1024 * 1024)).toFixed(2);
