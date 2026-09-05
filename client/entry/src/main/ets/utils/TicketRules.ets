import {
  ElectronicTicketStatus,
  TicketOrder,
  TicketOrderStatus,
  TicketSlot
} from '../models/TicketModels';

export enum TicketOrderAction {
  PAY = 'PAY',
  CANCEL = 'CANCEL',
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
  // 门票状态机把“占库存但未付款”和“已售出票”分开处理：取消只释放 reserved，退款才回补 sold。
  if (action === TicketOrderAction.PAY || action === TicketOrderAction.CANCEL) {
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
  if (action === TicketOrderAction.CANCEL) {
    return TicketOrderStatus.CANCELLED;
  }
  if (action === TicketOrderAction.REFUND) {
    return TicketOrderStatus.REFUNDED;
  }
  return status;
}

export function ticketOrderRenderKey(order: TicketOrder): string {
  // ArkUI 的 ForEach 会按 key 复用组件。改签不会改变 PAID 状态，闸机核验也不会改变
  // 订单状态，因此 key 还必须覆盖时段及每张电子票的状态，确保卡片立即重建。
  let ticketFingerprint: string = '';
  for (let index: number = 0; index < order.tickets.length; index++) {
    ticketFingerprint += `:${order.tickets[index].id}:${order.tickets[index].status}`;
  }
  return `${order.id}:${order.status}:${order.slot_id}:${order.visit_date}:${order.start_time}:` +
    `${order.end_time}:${order.refund_cutoff_hours}:${order.refund_deadline_at}:` +
    `${order.refundable}${ticketFingerprint}`;
}

export function hasRequiredIssuedTickets(order: TicketOrder): boolean {
  if (order.status !== TicketOrderStatus.PAID || order.tickets.length === 0) {
    return false;
  }
  let issuedCount: number = 0;
  for (let index: number = 0; index < order.tickets.length; index++) {
    if (order.tickets[index].status === ElectronicTicketStatus.ISSUED) {
      issuedCount++;
    }
  }
  // 改签会保留历史 VOID 票用于审计；只要当前 ISSUED 数量等于订单数量即可继续退改。
  return issuedCount === order.quantity;
}

export function canRefundTicketOrder(order: TicketOrder): boolean {
  return hasRequiredIssuedTickets(order) && order.refundable;
}

export function normalizeCachedTicketOrders(payload: string): TicketOrder[] {
  try {
    const orders: TicketOrder[] = JSON.parse(payload) as TicketOrder[];
    if (!Array.isArray(orders)) {
      return [];
    }
    for (let index: number = 0; index < orders.length; index++) {
      const order: TicketOrder = orders[index];
      // v1 缓存没有退款策略字段。显式补默认值，覆盖安装后离线打开订单不会把
      // undefined 传入时间格式器；旧缓存保持只读且不凭空获得退款资格。
      if (typeof order.refund_cutoff_hours !== 'number' || order.refund_cutoff_hours < 0) {
        order.refund_cutoff_hours = 0;
      }
      if (typeof order.refund_deadline_at !== 'string') {
        order.refund_deadline_at = null;
      }
      if (typeof order.refundable !== 'boolean') {
        order.refundable = false;
      }
      if (!Array.isArray(order.tickets)) {
        order.tickets = [];
      }
    }
    return orders;
  } catch (error) {
    return [];
  }
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
