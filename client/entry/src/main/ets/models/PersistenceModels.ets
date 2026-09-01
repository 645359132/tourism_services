import { ShopOrder, ShopOrderItem } from './ShopModels';
import { TicketQrResponse } from './TicketModels';

export class CachedTicketIdentity {
  ticket_id: string = '';
  ticket_code: string = '';
  expires_at: string = '';
  cached_at: string = '';
  scannable: boolean = false;

  static fromQr(value: TicketQrResponse): CachedTicketIdentity {
    const cached: CachedTicketIdentity = new CachedTicketIdentity();
    cached.ticket_id = value.ticket_id;
    cached.ticket_code = value.ticket_code;
    cached.expires_at = value.expires_at;
    cached.cached_at = new Date().toISOString();
    cached.scannable = false;
    return cached;
  }
}

export class OfflineProfile {
  schema_version: number = 1;
  user_id: string = '';
  display_name: string = '';
  saved_at: string = '';
}

export class OwnedCacheEnvelope {
  schema_version: number = 1;
  owner_user_id: string = '';
  payload: string = '';
}

export function createOwnedCacheEnvelope(userId: string, payload: string): string {
  if (userId.length === 0 || !isSafeTravelCachePayload(payload)) { return ''; }
  const envelope: OwnedCacheEnvelope = new OwnedCacheEnvelope();
  envelope.owner_user_id = userId;
  envelope.payload = payload;
  return JSON.stringify(envelope);
}

export function readOwnedCacheEnvelope(serialized: string, expectedUserId: string): string {
  if (serialized.length === 0 || expectedUserId.length === 0) { return ''; }
  try {
    const envelope: OwnedCacheEnvelope = JSON.parse(serialized) as OwnedCacheEnvelope;
    if (envelope.schema_version !== 1 || envelope.owner_user_id !== expectedUserId ||
      !isSafeTravelCachePayload(envelope.payload)) {
      return '';
    }
    return envelope.payload;
  } catch (error) {
    return '';
  }
}

export function deterministicPayloadFingerprint(payload: string): string {
  let hash: number = 17;
  for (let index: number = 0; index < payload.length; index++) {
    hash = (hash * 31 + payload.charCodeAt(index)) % 2147483647;
  }
  return `${payload.length}:${hash}`;
}

export class CachedShopOrderItem {
  product_name: string = '';
  quantity: number = 0;
  subtotal_cents: number = 0;

  static fromOrderItem(value: ShopOrderItem): CachedShopOrderItem {
    const cached: CachedShopOrderItem = new CachedShopOrderItem();
    cached.product_name = value.product_name;
    cached.quantity = value.quantity;
    cached.subtotal_cents = value.subtotal_cents;
    return cached;
  }
}

export class CachedShopOrder {
  id: string = '';
  order_no: string = '';
  status: string = '';
  total_quantity: number = 0;
  subtotal_cents: number = 0;
  discount_cents: number = 0;
  total_cents: number = 0;
  points_awarded: number = 0;
  items: CachedShopOrderItem[] = [];
  provider: string = '';
  is_demo: boolean = true;
  created_at: string = '';
  paid_at: string | null = null;
  expires_at: string | null = null;

  static fromOrder(value: ShopOrder): CachedShopOrder {
    const cached: CachedShopOrder = new CachedShopOrder();
    cached.id = value.id;
    cached.order_no = value.order_no;
    cached.status = value.status;
    cached.total_quantity = value.total_quantity;
    cached.subtotal_cents = value.subtotal_cents;
    cached.discount_cents = value.discount_cents;
    cached.total_cents = value.total_cents;
    cached.points_awarded = value.points_awarded;
    const items: CachedShopOrderItem[] = [];
    for (let index: number = 0; index < value.items.length; index++) {
      items.push(CachedShopOrderItem.fromOrderItem(value.items[index]));
    }
    cached.items = items;
    cached.provider = value.provider;
    cached.is_demo = value.is_demo;
    cached.created_at = value.created_at;
    cached.paid_at = value.paid_at;
    cached.expires_at = value.expires_at;
    return cached;
  }
}

export function isSafeTravelCachePayload(payload: string): boolean {
  const normalized: string = payload.toLowerCase();
  const forbidden: string[] = ['"qr_data"', '"delivery_phone"', '"delivery_address"',
    '"access_token"', '"refresh_token"', '"password"'];
  for (let index: number = 0; index < forbidden.length; index++) {
    if (normalized.includes(forbidden[index])) {
      return false;
    }
  }
  return true;
}
