import { common } from '@kit.AbilityKit';
import { preferences } from '@kit.ArkData';
import { Itinerary } from '../models/GuideModels';
import { ShopOrder } from '../models/ShopModels';
import { TicketOrder, TicketQrResponse } from '../models/TicketModels';
import { normalizeCachedTicketOrders } from '../utils/TicketRules';
import {
  CachedShopOrder,
  CachedTicketIdentity,
  OfflineProfile,
  createOwnedCacheEnvelope,
  readOwnedCacheEnvelope
} from '../models/PersistenceModels';

export class TravelPersistenceStore {
  // 创新点 7：离线数据集中落入 Preferences，但所有业务缓存仍按用户封装，防止账号切换后串读。
  private static instance: TravelPersistenceStore = new TravelPersistenceStore();
  private preferenceStore: preferences.Preferences | null = null;

  static getInstance(): TravelPersistenceStore {
    return TravelPersistenceStore.instance;
  }

  initialize(context: common.Context): void {
    try {
      const options: preferences.Options = { name: 'smart_tourism_travel_cache' };
      this.preferenceStore = preferences.getPreferencesSync(context, options);
    } catch (error) {
      this.preferenceStore = null;
    }
  }

  saveTicketOrders(userId: string, values: TicketOrder[]): void {
    this.writeOwnedJson('ticket_orders', userId, JSON.stringify(values));
  }

  saveOfflineProfile(userId: string, displayName: string): void {
    if (userId.length === 0) { return; }
    // 冷启动只保存最小身份提示信息；访问令牌和可直接核验的动态二维码不会写入该持久层。
    const profile: OfflineProfile = new OfflineProfile();
    profile.user_id = userId;
    profile.display_name = displayName;
    profile.saved_at = new Date().toISOString();
    this.writeString('offline_profile_v1', JSON.stringify(profile));
  }

  loadOfflineProfile(): OfflineProfile | null {
    const payload: string = this.readString('offline_profile_v1');
    if (payload.length === 0) { return null; }
    try {
      const profile: OfflineProfile = JSON.parse(payload) as OfflineProfile;
      return profile.schema_version === 1 && profile.user_id.length > 0 ? profile : null;
    } catch (error) {
      return null;
    }
  }

  clearOfflineProfile(): void {
    if (this.preferenceStore === null) { return; }
    try {
      this.preferenceStore.deleteSync('offline_profile_v1');
      this.preferenceStore.flushSync();
    } catch (error) {
    }
  }

  loadTicketOrders(userId: string): TicketOrder[] {
    const payload: string = this.readOwnedJson('ticket_orders', userId);
    if (payload.length === 0) {
      return [];
    }
    return normalizeCachedTicketOrders(payload);
  }

  saveTicketIdentity(userId: string, value: TicketQrResponse): void {
    this.writeOwnedJson('ticket_identity', userId, JSON.stringify(CachedTicketIdentity.fromQr(value)));
  }

  loadTicketIdentity(userId: string): CachedTicketIdentity | null {
    const payload: string = this.readOwnedJson('ticket_identity', userId);
    if (payload.length === 0) {
      return null;
    }
    try {
      return JSON.parse(payload) as CachedTicketIdentity;
    } catch (error) {
      return null;
    }
  }

  saveItinerary(userId: string, value: Itinerary): void {
    this.writeOwnedJson('itinerary', userId, JSON.stringify(value));
  }

  loadItinerary(userId: string): Itinerary | null {
    const payload: string = this.readOwnedJson('itinerary', userId);
    if (payload.length === 0) {
      return null;
    }
    try {
      return JSON.parse(payload) as Itinerary;
    } catch (error) {
      return null;
    }
  }

  saveShopOrders(userId: string, values: ShopOrder[]): void {
    const cached: CachedShopOrder[] = [];
    for (let index: number = 0; index < values.length; index++) {
      cached.push(CachedShopOrder.fromOrder(values[index]));
    }
    this.writeOwnedJson('shop_orders', userId, JSON.stringify(cached));
  }

  loadShopOrders(userId: string): CachedShopOrder[] {
    const payload: string = this.readOwnedJson('shop_orders', userId);
    if (payload.length === 0) {
      return [];
    }
    try {
      return JSON.parse(payload) as CachedShopOrder[];
    } catch (error) {
      return [];
    }
  }

  saveOfflinePack(userId: string, payload: string): void {
    this.writeOwnedJson('offline_pack', userId, payload);
  }

  loadOfflinePack(userId: string): string {
    return this.readOwnedJson('offline_pack', userId);
  }

  saveOfflineQueue(userId: string, payload: string): void {
    this.writeOwnedJson('offline_queue', userId, payload);
  }

  loadOfflineQueue(userId: string): string {
    return this.readOwnedJson('offline_queue', userId);
  }

  private writeOwnedJson(key: string, userId: string, payload: string): void {
    // 创新点 7：存储键和数据信封都绑定 userId；读取时再次验主，形成跨账号重放的双重边界。
    const envelope: string = createOwnedCacheEnvelope(userId, payload);
    if (envelope.length === 0) { return; }
    this.writeString(this.ownedKey(key, userId), envelope);
  }

  private readOwnedJson(key: string, userId: string): string {
    return readOwnedCacheEnvelope(this.readString(this.ownedKey(key, userId)), userId);
  }

  private ownedKey(key: string, userId: string): string {
    return `owned_v1_${key}_${userId}`;
  }

  private writeString(key: string, value: string): void {
    if (this.preferenceStore === null) {
      return;
    }
    try {
      this.preferenceStore.putSync(key, value);
      this.preferenceStore.flushSync();
    } catch (error) {
    }
  }

  private readString(key: string): string {
    if (this.preferenceStore === null) {
      return '';
    }
    try {
      const value: preferences.ValueType = this.preferenceStore.getSync(key, '');
      return typeof value === 'string' ? value : '';
    } catch (error) {
      return '';
    }
  }
}
