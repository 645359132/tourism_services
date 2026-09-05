import { CartItem, PointsReward, ShopOrder, ShopOrderStatus, ShopProduct } from '../models/ShopModels';

export class ShopRuleResult {
  valid: boolean;
  message: string;

  constructor(valid: boolean, message: string) {
    this.valid = valid;
    this.message = message;
  }
}

export function effectiveProductPrice(product: ShopProduct): number {
  if (product.effective_price_cents > 0 && product.effective_price_cents <= product.price_cents) {
    return product.effective_price_cents;
  }
  return product.price_cents;
}

export function shopProductRenderKey(product: ShopProduct): string {
  // ShopProduct 不是 @Observed；库存或活动价变化时必须更换 ForEach key 才会重建卡片。
  return `${product.id}:${product.stock}:${product.price_cents}:${product.effective_price_cents}:` +
    `${product.campaign_id ?? ''}`;
}

export function cartItemRenderKey(item: CartItem): string {
  return `${item.id}:${item.quantity}:${item.stock}:${item.unit_price_cents}:${item.subtotal_cents}`;
}

export function shopOrderRenderKey(order: ShopOrder): string {
  return `${order.id}:${order.status}:${order.points_awarded}:${order.expires_at ?? ''}`;
}

export function pointsRewardRenderKey(reward: PointsReward): string {
  return `${reward.id}:${reward.stock}:${reward.points_cost}`;
}

export function validateCartQuantity(quantity: number, stock: number): ShopRuleResult {
  if (!Number.isInteger(quantity) || quantity < 1 || quantity > 99) {
    return new ShopRuleResult(false, '商品数量应为 1 至 99 件');
  }
  if (stock <= 0) {
    return new ShopRuleResult(false, '商品已售罄');
  }
  if (quantity > stock) {
    return new ShopRuleResult(false, `当前仅剩 ${stock} 件`);
  }
  return new ShopRuleResult(true, '');
}

export function validateCheckout(items: CartItem[], name: string, phone: string, province: string,
  city: string, addressLine: string): ShopRuleResult {
  if (items.length === 0) {
    return new ShopRuleResult(false, '购物车为空');
  }
  if (name.trim().length < 1 || name.trim().length > 100) {
    return new ShopRuleResult(false, '收货人姓名应为 1 至 100 个字符');
  }
  if (phone.trim().length < 6 || phone.trim().length > 32) {
    return new ShopRuleResult(false, '联系电话应为 6 至 32 个字符');
  }
  if (province.trim().length === 0 || province.trim().length > 80 || city.trim().length === 0 ||
    city.trim().length > 80) {
    return new ShopRuleResult(false, '请填写省份和城市');
  }
  if (addressLine.trim().length < 3 || addressLine.trim().length > 300) {
    return new ShopRuleResult(false, '详细地址应为 3 至 300 个字符');
  }
  for (let index: number = 0; index < items.length; index++) {
    const validation: ShopRuleResult = validateCartQuantity(items[index].quantity, items[index].stock);
    if (!validation.valid) {
      return validation;
    }
  }
  return new ShopRuleResult(true, '');
}

export function canPayShopOrder(status: ShopOrderStatus): boolean {
  return status === ShopOrderStatus.PENDING_PAYMENT;
}

export function validateRewardRedemption(accountBalance: number, reward: PointsReward | null): ShopRuleResult {
  if (reward === null) {
    return new ShopRuleResult(false, '请选择积分奖励');
  }
  if (reward.stock <= 0) {
    return new ShopRuleResult(false, '该奖励已兑完');
  }
  if (accountBalance < reward.points_cost) {
    return new ShopRuleResult(false, `积分不足，还差 ${reward.points_cost - accountBalance} 分`);
  }
  return new ShopRuleResult(true, '');
}

export function validateShare(contentType: string, refId: string, caption: string): ShopRuleResult {
  if (contentType.trim().length === 0 || refId.trim().length === 0) {
    return new ShopRuleResult(false, '请选择要分享的内容');
  }
  if (caption.trim().length < 3 || caption.trim().length > 200) {
    return new ShopRuleResult(false, '分享文案应为 3 至 200 个字符');
  }
  return new ShopRuleResult(true, '');
}
