import {
  ExperienceSession,
  QueueEventEnvelope,
  QueueStatus,
  Reservation,
  ReservationStatus,
  SessionStatus
} from '../models/BookingModels';

export class BookingRuleResult {
  valid: boolean;
  message: string;

  constructor(valid: boolean, message: string) {
    this.valid = valid;
    this.message = message;
  }
}

export class SessionInventoryChange {
  changed: boolean;
  depleted: boolean;
  message: string;

  constructor(changed: boolean, depleted: boolean, message: string) {
    this.changed = changed;
    this.depleted = depleted;
    this.message = message;
  }
}

export class QueueEventParseResult {
  valid: boolean;
  message: string;
  envelope: QueueEventEnvelope | null;

  constructor(valid: boolean, message: string, envelope: QueueEventEnvelope | null) {
    this.valid = valid;
    this.message = message;
    this.envelope = envelope;
  }
}

export function validateBookingDate(value: string): BookingRuleResult {
  const match: RegExpMatchArray | null = value.match(/^([0-9]{4})-([0-9]{2})-([0-9]{2})$/);
  if (match === null) {
    return new BookingRuleResult(false, '日期格式应为 YYYY-MM-DD');
  }
  const year: number = Number(match[1]);
  const month: number = Number(match[2]);
  const day: number = Number(match[3]);
  const parsed: Date = new Date(Date.UTC(year, month - 1, day));
  if (parsed.getUTCFullYear() !== year || parsed.getUTCMonth() !== month - 1 || parsed.getUTCDate() !== day) {
    return new BookingRuleResult(false, '请选择有效日期');
  }
  return new BookingRuleResult(true, '');
}

function twoDigitDatePart(value: number): string {
  return value < 10 ? `0${value.toString()}` : value.toString();
}

export function shanghaiDateAfterDays(days: number, nowMs: number = Date.now()): string {
  const shanghaiOffsetMs: number = 8 * 60 * 60 * 1000;
  const dayMs: number = 24 * 60 * 60 * 1000;
  const localClock: Date = new Date(nowMs + shanghaiOffsetMs + days * dayMs);
  return `${localClock.getUTCFullYear().toString()}-${twoDigitDatePart(localClock.getUTCMonth() + 1)}-` +
    `${twoDigitDatePart(localClock.getUTCDate())}`;
}

export function validateSessionReservation(session: ExperienceSession | null, partySize: number): BookingRuleResult {
  if (session === null) {
    return new BookingRuleResult(false, '请先选择场次');
  }
  if (session.status !== SessionStatus.OPEN) {
    return new BookingRuleResult(false, '当前场次不可预约');
  }
  if (!Number.isInteger(partySize) || partySize < 1 || partySize > 8) {
    return new BookingRuleResult(false, '同行人数应为 1 至 8 人');
  }
  if (partySize > session.remaining) {
    return new BookingRuleResult(false, `场次仅剩 ${session.remaining} 个名额`);
  }
  return new BookingRuleResult(true, '');
}

export function detectSessionInventoryChange(previous: ExperienceSession | null,
  current: ExperienceSession): SessionInventoryChange {
  if (previous === null || previous.id !== current.id || previous.remaining === current.remaining) {
    return new SessionInventoryChange(false, current.remaining === 0, '');
  }
  if (current.remaining === 0) {
    return new SessionInventoryChange(true, true, '所选场次已满，请选择其他场次');
  }
  return new SessionInventoryChange(true, false, `场次库存已更新，当前剩余 ${current.remaining} 个名额`);
}

export function hasReservationConflict(reservations: Reservation[], startsAt: string, endsAt: string): boolean {
  for (let reservationIndex: number = 0; reservationIndex < reservations.length; reservationIndex++) {
    const reservation: Reservation = reservations[reservationIndex];
    if (reservation.status !== ReservationStatus.HELD && reservation.status !== ReservationStatus.CONFIRMED) {
      continue;
    }
    for (let allocationIndex: number = 0; allocationIndex < reservation.allocations.length; allocationIndex++) {
      const allocation = reservation.allocations[allocationIndex];
      if (startsAt < allocation.ends_at && endsAt > allocation.starts_at) {
        return true;
      }
    }
  }
  return false;
}

export function shouldAcceptQueueSequence(currentSequence: number, incomingSequence: number): boolean {
  return incomingSequence > currentSequence;
}

export function shouldAcceptQueueEvent(currentSequence: number, incomingSequence: number,
  eventType: string): boolean {
  if (incomingSequence > currentSequence) {
    return true;
  }
  if (incomingSequence < currentSequence) {
    return false;
  }
  return eventType === 'nearby.recommended' || eventType === 'itinerary.replan_available';
}

export function isCurrentItinerarySuggestion(currentId: string, currentRevision: number,
  suggestionId: string | null, suggestionRevision: number | null): boolean {
  return suggestionId !== null && suggestionRevision !== null && suggestionId === currentId &&
    suggestionRevision === currentRevision;
}

export function isTerminalQueueStatus(status: QueueStatus): boolean {
  return status === QueueStatus.COMPLETED || status === QueueStatus.LEFT || status === QueueStatus.EXPIRED;
}

export function parseQueueEvent(payload: string): QueueEventParseResult {
  try {
    const envelope: QueueEventEnvelope = JSON.parse(payload) as QueueEventEnvelope;
    const knownType: boolean = envelope.type === 'queue.updated' || envelope.type === 'nearby.recommended' ||
      envelope.type === 'itinerary.replan_available';
    if (envelope.id.length === 0 || !knownType || envelope.occurred_at.length === 0) {
      return new QueueEventParseResult(false, '队列事件信封字段无效', null);
    }
    if (envelope.data.queue.id.length === 0 || envelope.data.queue.sequence < 0 ||
      envelope.data.source !== 'simulated' || !envelope.data.is_demo) {
      return new QueueEventParseResult(false, '队列事件边界字段无效', null);
    }
    return new QueueEventParseResult(true, '', envelope);
  } catch (error) {
    return new QueueEventParseResult(false, '队列事件不是有效 JSON', null);
  }
}

export function validateStayBooking(checkIn: string, checkOut: string, quantity: number,
  partySize: number): BookingRuleResult {
  if (!validateBookingDate(checkIn).valid || !validateBookingDate(checkOut).valid || checkIn >= checkOut) {
    return new BookingRuleResult(false, '住宿离店日期必须晚于入住日期');
  }
  if (quantity < 1 || quantity > 4 || partySize < 1 || partySize > 12) {
    return new BookingRuleResult(false, '请检查房间数量和入住人数');
  }
  return new BookingRuleResult(true, '');
}

export function validateTimedBooking(startsAt: string, partySize: number): BookingRuleResult {
  if (startsAt.length < 16 || partySize < 1 || partySize > 12) {
    return new BookingRuleResult(false, '请选择有效时段并检查同行人数');
  }
  return new BookingRuleResult(true, '');
}

export function validateReview(rating: number, content: string): BookingRuleResult {
  if (!Number.isInteger(rating) || rating < 1 || rating > 5) {
    return new BookingRuleResult(false, '评分应为 1 至 5 星');
  }
  if (content.trim().length < 3 || content.trim().length > 500) {
    return new BookingRuleResult(false, '评价内容应为 3 至 500 个字符');
  }
  return new BookingRuleResult(true, '');
}
