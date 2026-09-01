export enum ShopOrderStatus {
  PENDING_PAYMENT = 'PENDING_PAYMENT',
  PAID = 'PAID',
  FULFILLING = 'FULFILLING',
  SHIPPED = 'SHIPPED',
  COMPLETED = 'COMPLETED',
  CANCELLED = 'CANCELLED',
  EXPIRED = 'EXPIRED'
}

export class ShopCategory {
  id: string = '';
  code: string = '';
  name: string = '';
  description: string = '';
  sort_order: number = 0;
}

export class ShopCategoryListResponse {
  items: ShopCategory[] = [];
}

export class ShopCampaign {
  id: string = '';
  code: string = '';
  name: string = '';
  description: string = '';
  product_id: string | null = null;
  category_id: string | null = null;
  starts_at: string = '';
  ends_at: string = '';
  discount_bps: number = 0;
  is_demo: boolean = true;
}

export class ShopCampaignListResponse {
  items: ShopCampaign[] = [];
}

export class ShopProduct {
  id: string = '';
  category_id: string = '';
  sku: string = '';
  name: string = '';
  description: string = '';
  price_cents: number = 0;
  effective_price_cents: number = 0;
  stock: number = 0;
  points_price: number | null = null;
  tags: string[] = [];
  campaign_id: string | null = null;
  campaign_name: string | null = null;
  provider: string = 'demo';
  is_demo: boolean = true;
}

export class ShopProductListResponse {
  items: ShopProduct[] = [];
}

export class CartItem {
  id: string = '';
  product_id: string = '';
  product_name: string = '';
  sku: string = '';
  quantity: number = 0;
  stock: number = 0;
  unit_price_cents: number = 0;
  subtotal_cents: number = 0;
}

export class ShoppingCart {
  id: string = '';
  items: CartItem[] = [];
  total_quantity: number = 0;
  subtotal_cents: number = 0;
  discount_cents: number = 0;
  total_cents: number = 0;
  updated_at: string = '';
}

export class ShopOrderItem {
  product_id: string = '';
  product_name: string = '';
  sku: string = '';
  quantity: number = 0;
  unit_price_cents: number = 0;
  subtotal_cents: number = 0;
}

export class ShopOrder {
  id: string = '';
  order_no: string = '';
  status: ShopOrderStatus = ShopOrderStatus.PENDING_PAYMENT;
  items: ShopOrderItem[] = [];
  total_quantity: number = 0;
  subtotal_cents: number = 0;
  discount_cents: number = 0;
  total_cents: number = 0;
  points_awarded: number = 0;
  delivery_name: string = '';
  delivery_phone: string = '';
  delivery_address: string = '';
  provider: string = 'demo';
  is_demo: boolean = true;
  created_at: string = '';
  paid_at: string | null = null;
  expires_at: string | null = null;
}

export class ShopOrderListResponse {
  items: ShopOrder[] = [];
}

export class PointsAccount {
  balance: number = 0;
  updated_at: string = '';
}

export class PointsLedgerEntry {
  id: string = '';
  kind: string = '';
  amount: number = 0;
  balance_after: number = 0;
  reason: string = '';
  reference_type: string = '';
  reference_id: string = '';
  created_at: string = '';
}

export class PointsLedgerResponse {
  items: PointsLedgerEntry[] = [];
}

export class PointsReward {
  id: string = '';
  code: string = '';
  name: string = '';
  description: string = '';
  points_cost: number = 0;
  stock: number = 0;
  provider: string = 'demo';
  is_demo: boolean = true;
}

export class PointsRewardListResponse {
  items: PointsReward[] = [];
}

export class PointsRedemption {
  id: string = '';
  redemption_no: string = '';
  reward_id: string = '';
  reward_name: string = '';
  points_spent: number = 0;
  status: string = '';
  created_at: string = '';
}

export class ShareRecord {
  id: string = '';
  content_type: string = '';
  ref_id: string = '';
  platform: string = '';
  caption: string = '';
  points_awarded: number = 0;
  provider: string = 'demo';
  is_demo: boolean = true;
  created_at: string = '';
}
