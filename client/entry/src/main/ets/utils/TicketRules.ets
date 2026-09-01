import { TicketOrderStatus, TicketSlot } from '../models/TicketModels';

export enum TicketOrderAction {
  PAY = 'PAY',
  REFUND = 'REFUND',
  RESCHEDULE = 'RESCHEDULE',
  SHOW_QR = 'SHOW_QR'
}

export class TicketRuleResult {
  valid: boolean;
  message: string;

  constructor(valid: boolean, message: string) {
    this.valid = valid;
    this.message = message;
  }
}

export class InventoryChangeResult {
  changed: boolean;
  depleted: boolean;
  priceChanged: boolean;
  message: string;

  constructor(changed: boolean, depleted: boolean, priceChanged: boolean, message: string) {
    this.changed = changed;
    this.depleted = depleted;
    this.priceChanged = priceChanged;
    this.message = message;
  }
}

export class PendingIdempotentOperation {
  private operationId: string = '';
  private idempotencyKey: string = '';

  getOrCreate(operationId: string, prefix: string): string {
    if (this.operationId !== operationId || this.idempotencyKey.length === 0) {
      this.operationId = operationId;
      this.idempotencyKey = createIdempotencyKey(prefix);
    }
    return this.idempotencyKey;
  }

  resolveSuccess(): void {
    this.clear();
  }

  resolveFailure(statusCode: number, retriable: boolean): void {
    const definitiveBusinessFailure: boolean = statusCode >= 400 && statusCode < 500 && !retriable;
    if (definitiveBusinessFailure) {
      this.clear();
    }
  }

  getOperationId(): string {
    return this.operationId;
  }

  getKey(): string {
    return this.idempotencyKey;
  }

  private clear(): void {
    this.operationId = '';
    this.idempotencyKey = '';
  }
}

export function formatMoney(cents: number): string {
  return `¥${(Math.max(0, cents) / 100).toFixed(2)}`;
}

export function validateVisitDate(value: string): TicketRuleResult {
  const match: RegExpMatchArray | null = value.match(/^([0-9]{4})-([0-9]{2})-([0-9]{2})$/);
  if (match === null) {
    return new TicketRuleResult(false, '日期格式应为 YYYY-MM-DD');
  }
  const year: number = Number(match[1]);
  const month: number = Number(match[2]);
  const day: number = Number(match[3]);
  const parsed: Date = new Date(Date.UTC(year, month - 1, day));
  if (parsed.getUTCFullYear() !== year || parsed.getUTCMonth() !== month - 1 || parsed.getUTCDate() !== day) {
    return new TicketRuleResult(false, '请选择有效日期');
  }
  return new TicketRuleResult(true, '');
}

export function validateTicketQuantity(quantity: number, remaining: number): TicketRuleResult {
  if (!Number.isInteger(quantity) || quantity < 1 || quantity > 8) {
    return new TicketRuleResult(false, '单次购票数量应为 1 至 8 张');
  }
  if (remaining <= 0) {
    return new TicketRuleResult(false, '当前时段已售罄');
  }
  if (quantity > remaining) {
    return new TicketRuleResult(false, `当前仅剩 ${remaining} 张，请调整数量`);
  }
  return new TicketRuleResult(true, '');
}

export function canApplyTicketAction(status: TicketOrderStatus, action: TicketOrderAction): boolean {
  if (action === TicketOrderAction.PAY) {
    return status === TicketOrderStatus.PENDING_PAYMENT;
  }
  if (action === TicketOrderAction.REFUND || action === TicketOrderAction.RESCHEDULE ||
    action === TicketOrderAction.SHOW_QR) {
    return status === TicketOrderStatus.PAID;
  }
  return false;
}

export function transitionTicketOrderStatus(status: TicketOrderStatus,
  action: TicketOrderAction): TicketOrderStatus {
  if (!canApplyTicketAction(status, action)) {
    return status;
  }
  if (action === TicketOrderAction.PAY) {
    return TicketOrderStatus.PAID;
  }
  if (action === TicketOrderAction.REFUND) {
    return TicketOrderStatus.REFUNDED;
  }
  return status;
}

export function detectInventoryChange(previous: TicketSlot | null, current: TicketSlot): InventoryChangeResult {
  if (previous === null || previous.id !== current.id) {
    return new InventoryChangeResult(false, current.remaining === 0, false, '');
  }
  const remainingChanged: boolean = previous.remaining !== current.remaining;
  const priceChanged: boolean = previous.unit_price_cents !== current.unit_price_cents;
  if (!remainingChanged && !priceChanged) {
    return new InventoryChangeResult(false, current.remaining === 0, false, '');
  }
  if (current.remaining === 0) {
    return new InventoryChangeResult(true, true, priceChanged, '所选时段库存已售罄，请选择其他时段');
  }
  if (priceChanged && remainingChanged) {
    return new InventoryChangeResult(true, false, true,
      `库存更新为 ${current.remaining} 张，动态价格已调整为 ${formatMoney(current.unit_price_cents)}`);
  }
  if (priceChanged) {
    return new InventoryChangeResult(true, false, true,
      `动态价格已调整为 ${formatMoney(current.unit_price_cents)}，请重新报价`);
  }
  return new InventoryChangeResult(true, false, false, `库存已更新，当前剩余 ${current.remaining} 张`);
}

export function createIdempotencyKey(prefix: string): string {
  const randomPart: string = Math.floor(Math.random() * 1000000).toString();
  return `${prefix}-${Date.now().toString()}-${randomPart}`;
}
