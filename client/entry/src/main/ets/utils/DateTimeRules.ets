const SHANGHAI_OFFSET_MS: number = 8 * 60 * 60 * 1000;

function normalizedApiTimestamp(value: string): string {
  const trimmed: string = value.trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(trimmed)) {
    return trimmed;
  }
  if (/Z$|[+-]\d{2}:\d{2}$/.test(trimmed)) {
    return trimmed;
  }
  // SQLite 可能把 timezone=True 字段读成无偏移 ISO；API 约定这些旧值仍表示 UTC。
  return `${trimmed}Z`;
}

export function formatShanghaiDateTime(value: string): string {
  const normalized: string = normalizedApiTimestamp(value);
  if (/^\d{4}-\d{2}-\d{2}$/.test(normalized)) {
    return normalized;
  }
  const parsed: number = Date.parse(normalized);
  if (Number.isNaN(parsed)) {
    return '时间待定';
  }
  // 上海全年固定 UTC+8，无夏令时；使用 UTC getter 可避免模拟器自身时区再次参与换算。
  const scenicClock: string = new Date(parsed + SHANGHAI_OFFSET_MS).toISOString();
  return `${scenicClock.substring(0, 10)} ${scenicClock.substring(11, 16)}`;
}

export function formatShanghaiTime(value: string): string {
  const formatted: string = formatShanghaiDateTime(value);
  return formatted.length >= 16 && formatted.substring(10, 11) === ' ' ? formatted.substring(11, 16) : '时间待定';
}

export function formatShanghaiRange(startsAt: string, endsAt: string): string {
  const start: string = formatShanghaiDateTime(startsAt);
  const end: string = formatShanghaiDateTime(endsAt);
  if (start === '时间待定' || end === '时间待定' || start.length < 16 || end.length < 16) {
    return '时间待定';
  }
  return start.substring(0, 10) === end.substring(0, 10) ?
    `${start}–${end.substring(11, 16)}` : `${start}–${end.substring(5, 16)}`;
}

export function formatScenicClock(value: string): string {
  const match: RegExpMatchArray | null = value.trim().match(/^([01]\d|2[0-3]):([0-5]\d)/);
  return match === null ? '时间待定' : `${match[1]}:${match[2]}`;
}
