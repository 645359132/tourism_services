import {
  PointsAccount,
  PointsLedgerResponse,
  PointsRedemption,
  PointsRewardListResponse,
  ShareRecord,
  ShopCampaignListResponse,
  ShopCategoryListResponse,
  ShopOrder,
  ShopOrderListResponse,
  ShopProductListResponse,
  ShoppingCart
} from '../../models/ShopModels';
import { ApiMethod, ApiRequest, HttpClient, NetworkResult } from '../HttpClient';

class CartItemPayload {
  product_id: string;
  quantity: number;
  constructor(productId: string, quantity: number) { this.product_id = productId; this.quantity = quantity; }
}

class CartQuantityPayload {
  quantity: number;
  constructor(quantity: number) { this.quantity = quantity; }
}

class DeliveryPayload {
  name: string;
  phone: string;
  province: string;
  city: string;
  address_line: string;
  postal_code: string | null;
  constructor(name: string, phone: string, province: string, city: string, addressLine: string,
    postalCode: string | null) {
    this.name = name; this.phone = phone; this.province = province; this.city = city;
    this.address_line = addressLine; this.postal_code = postalCode;
  }
}

class CheckoutPayload {
  delivery: DeliveryPayload;
  idempotency_key: string;
  constructor(name: string, phone: string, province: string, city: string, addressLine: string,
    postalCode: string | null, key: string) {
    this.delivery = new DeliveryPayload(name, phone, province, city, addressLine, postalCode);
    this.idempotency_key = key;
  }
}

class IdempotencyPayload {
  idempotency_key: string;
  constructor(key: string) { this.idempotency_key = key; }
}

class RedeemPayload {
  reward_id: string;
  idempotency_key: string;
  constructor(rewardId: string, key: string) { this.reward_id = rewardId; this.idempotency_key = key; }
}

class SharePayload {
  content_type: string;
  ref_id: string;
  platform: string;
  caption: string;
  idempotency_key: string;
  constructor(contentType: string, refId: string, platform: string, caption: string, key: string) {
    this.content_type = contentType; this.ref_id = refId; this.platform = platform;
    this.caption = caption; this.idempotency_key = key;
  }
}

export class ShopService {
  private client: HttpClient = new HttpClient();

  listCategories(): Promise<NetworkResult<ShopCategoryListResponse>> {
    return this.client.request<ShopCategoryListResponse>(new ApiRequest('/shop/categories', ApiMethod.GET, '', false));
  }

  listProducts(categoryId: string = ''): Promise<NetworkResult<ShopProductListResponse>> {
    const path: string = categoryId.length > 0 ? `/shop/products?category_id=${encodeURIComponent(categoryId)}` :
      '/shop/products';
    return this.client.request<ShopProductListResponse>(new ApiRequest(path, ApiMethod.GET, '', false));
  }

  listCampaigns(): Promise<NetworkResult<ShopCampaignListResponse>> {
    return this.client.request<ShopCampaignListResponse>(new ApiRequest('/shop/campaigns', ApiMethod.GET, '', false));
  }

  getCart(): Promise<NetworkResult<ShoppingCart>> {
    return this.client.request<ShoppingCart>(new ApiRequest('/shop/cart', ApiMethod.GET));
  }

  addCartItem(productId: string, quantity: number): Promise<NetworkResult<ShoppingCart>> {
    return this.client.request<ShoppingCart>(new ApiRequest('/shop/cart/items', ApiMethod.POST,
      JSON.stringify(new CartItemPayload(productId, quantity)), true, 0));
  }

  updateCartItem(itemId: string, quantity: number): Promise<NetworkResult<ShoppingCart>> {
    return this.client.request<ShoppingCart>(new ApiRequest(`/shop/cart/items/${encodeURIComponent(itemId)}`,
      ApiMethod.PUT, JSON.stringify(new CartQuantityPayload(quantity)), true, 0));
  }

  removeCartItem(itemId: string): Promise<NetworkResult<ShoppingCart>> {
    return this.client.request<ShoppingCart>(new ApiRequest(`/shop/cart/items/${encodeURIComponent(itemId)}`,
      ApiMethod.DELETE, '', true, 0));
  }

  checkout(name: string, phone: string, province: string, city: string, addressLine: string,
    postalCode: string, key: string): Promise<NetworkResult<ShopOrder>> {
    const normalizedPostalCode: string | null = postalCode.trim().length === 0 ? null : postalCode.trim();
    return this.client.request<ShopOrder>(new ApiRequest('/shop/cart/checkout', ApiMethod.POST,
      JSON.stringify(new CheckoutPayload(name, phone, province, city, addressLine, normalizedPostalCode, key)), true, 0));
  }

  listOrders(): Promise<NetworkResult<ShopOrderListResponse>> {
    return this.client.request<ShopOrderListResponse>(new ApiRequest('/shop/orders', ApiMethod.GET));
  }

  getOrder(orderId: string): Promise<NetworkResult<ShopOrder>> {
    return this.client.request<ShopOrder>(new ApiRequest(`/shop/orders/${encodeURIComponent(orderId)}`, ApiMethod.GET));
  }

  payOrder(orderId: string, key: string): Promise<NetworkResult<ShopOrder>> {
    return this.client.request<ShopOrder>(new ApiRequest(`/shop/orders/${encodeURIComponent(orderId)}/pay`,
      ApiMethod.POST, JSON.stringify(new IdempotencyPayload(key)), true, 0));
  }

  getPointsAccount(): Promise<NetworkResult<PointsAccount>> {
    return this.client.request<PointsAccount>(new ApiRequest('/points/account', ApiMethod.GET));
  }

  listPointsLedger(): Promise<NetworkResult<PointsLedgerResponse>> {
    return this.client.request<PointsLedgerResponse>(new ApiRequest('/points/ledger', ApiMethod.GET));
  }

  listRewards(): Promise<NetworkResult<PointsRewardListResponse>> {
    return this.client.request<PointsRewardListResponse>(new ApiRequest('/points/rewards', ApiMethod.GET));
  }

  redeemReward(rewardId: string, key: string): Promise<NetworkResult<PointsRedemption>> {
    return this.client.request<PointsRedemption>(new ApiRequest('/points/redeem', ApiMethod.POST,
      JSON.stringify(new RedeemPayload(rewardId, key)), true, 0));
  }

  shareContent(contentType: string, refId: string, platform: string, caption: string,
    key: string): Promise<NetworkResult<ShareRecord>> {
    return this.client.request<ShareRecord>(new ApiRequest('/shares', ApiMethod.POST,
      JSON.stringify(new SharePayload(contentType, refId, platform, caption, key)), true, 0));
  }
}
