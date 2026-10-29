import type { LogRecord } from './types';

export const MAX_RECORDS = 10000;
export const MAX_BYTES = 8 * 1024 * 1024;
const RECORD_OVERHEAD = 64;

export function recordBytes(record: LogRecord): number {
  let size = RECORD_OVERHEAD + record.event.length + record.timestamp.length + record.source.length;
  for (const key in record.fields) size += key.length + (record.fields[key]?.length ?? 0);
  for (const line of record.lines) size += line.length;
  return size;
}

export function joinContinuation(into: LogRecord, tail: LogRecord): LogRecord {
  return {
    ...into,
    lines: [...into.lines, tail.event, ...tail.lines],
    dropped_lines: into.dropped_lines + tail.dropped_lines,
    traceback: into.traceback || tail.traceback,
  };
}

export class RecordBuffer {
  records: LogRecord[] = [];
  bytes = 0;
  dropped = 0;
  refused = 0;
  private readonly maxRecords: number;
  private readonly maxBytes: number;

  constructor(maxRecords: number = MAX_RECORDS, maxBytes: number = MAX_BYTES) {
    this.maxRecords = maxRecords;
    this.maxBytes = maxBytes;
  }

  clear(): void {
    this.records = [];
    this.bytes = 0;
    this.dropped = 0;
    this.refused = 0;
  }

  append(incoming: readonly LogRecord[]): number {
    let added = 0;
    for (const record of incoming) {
      const last = this.records[this.records.length - 1];
      if (record.continues && last && added === 0) {
        const joined = joinContinuation(last, record);
        this.bytes += recordBytes(joined) - recordBytes(last);
        this.records[this.records.length - 1] = joined;
        continue;
      }
      this.records.push(record);
      this.bytes += recordBytes(record);
      added += 1;
    }
    this.trimFront();
    return added;
  }

  prepend(older: readonly LogRecord[]): number {
    const page = [...older];
    const first = this.records[0];
    const last = page[page.length - 1];
    const joins = Boolean(first?.continues && last);
    if (joins) page[page.length - 1] = joinContinuation(last as LogRecord, first as LogRecord);
    const held = joins ? this.records.slice(1) : this.records;
    const kept: LogRecord[] = [];
    let bytes = joins ? this.bytes - recordBytes(first as LogRecord) : this.bytes;
    for (let i = page.length - 1; i >= 0; i -= 1) {
      const record = page[i] as LogRecord;
      const size = recordBytes(record);
      if (held.length + kept.length >= this.maxRecords || bytes + size > this.maxBytes) {
        this.refused += i + 1;
        break;
      }
      kept.push(record);
      bytes += size;
    }
    if (kept.length === 0) return 0;
    kept.reverse();
    this.records = [...kept, ...held];
    this.bytes = bytes;
    return kept.length;
  }

  private trimFront(): void {
    let cut = 0;
    let bytes = this.bytes;
    while (cut < this.records.length && (this.records.length - cut > this.maxRecords || bytes > this.maxBytes)) {
      bytes -= recordBytes(this.records[cut] as LogRecord);
      cut += 1;
    }
    if (cut === 0) return;
    this.records = this.records.slice(cut);
    this.bytes = bytes;
    this.dropped += cut;
  }
}
