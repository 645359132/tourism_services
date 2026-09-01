import { StatePanel } from '../StatePanel';
import { ContentState } from '../../models/AppModels';
import { Itinerary } from '../../models/GuideModels';
import {
  AppliedSyncRecord,
  CachedOfflineAsset,
  CachedGuidance,
  EmergencyAckPayload,
  EmergencyBulletin,
  EmergencyBulletinListResponse,
  EmergencyResource,
  EmergencyResourceListResponse,
  ItineraryAckPayload,
  JourneyJsonPayload,
  LocalSosDraft,
  NoteMutationPayload,
  OfflineAssetContent,
  OfflineManifest,
  OfflineMutation,
  OfflineMutationStatus,
  OfflineOutbox,
  OfflineOutboxItem,
  OfflinePack,
  OfflinePackCache,
  OfflineTravelState,
  SosListResponse,
  SosRecord,
  SyncMutation,
  SyncPullResponse,
  SyncPushResponse,
  SyncPushResult,
  SyncStatusResponse
} from '../../models/JourneyModels';
import { CachedShopOrder, CachedTicketIdentity } from '../../models/PersistenceModels';
import { TicketOrder } from '../../models/TicketModels';
import { ApiErrorCode, ApiErrorInfo } from '../../network/ApiError';
import { NetworkResult } from '../../network/HttpClient';
import { JourneyService } from '../../network/services/JourneyService';
import { AppStore } from '../../stores/AppStore';
import { AuthStore } from '../../stores/AuthStore';
import { NetworkQuality, NetworkStore } from '../../stores/NetworkStore';
import { TravelPersistenceStore } from '../../stores/TravelPersistenceStore';
import {
  JourneyRuleResult,
  SyncFailureDisposition,
  assetMatchesManifest,
  classifySyncFailure,
  extractCachedGuidance,
  isOfflineCacheValid,
  isSafeOfflineMutation,
  manifestFingerprint,
  markOutboxFailure,
  mergeAppliedSyncRecords,
  offlineStateLabel,
  removeAppliedOutboxItems,
  shouldUseCachedManifest,
  validateSos
} from '../../utils/JourneyRules';
import { PendingIdempotentOperation } from '../../utils/TicketRules';
import { isWideWindow } from '../../utils/ResponsiveRules';
import { deterministicPayloadFingerprint, OfflineProfile } from '../../models/PersistenceModels';

@Component
export struct OfflineEmergencyView {
  @Prop loggedIn: boolean = false;
  onLoginTap: () => void = (): void => {};
  @State travelState: OfflineTravelState = OfflineTravelState.NO_PACK;
  @State cache: OfflinePackCache | null = null;
  @State outbox: OfflineOutbox = new OfflineOutbox();
  @State resources: EmergencyResource[] = [];
  @State bulletins: EmergencyBulletin[] = [];
  @State sosRecords: SosRecord[] = [];
  @State noteTitle: string = '离线旅行便签';
  @State noteText: string = '';
  @State sosKind: string = 'MEDICAL';
  @State sosMessage: string = '需要景区工作人员协助';
  @State sosNodeId: string = '';
  @State sosLatitude: string = '';
  @State sosLongitude: string = '';
  @State networkQuality: NetworkQuality = NetworkQuality.ONLINE;
  @State operationBusy: boolean = false;
  @State operationMessage: string = '';
  @State isWide: boolean = false;
  @State cachedTicketCount: number = 0;
  @State cachedTicketCode: string = '';
  @State cachedItineraryName: string = '';
  @State cachedShopOrderCount: number = 0;
  @State cachedEmergencySteps: string[] = [];
  @State cachedGuideSections: string[] = [];
  @State cachedMapNodes: string[] = [];
  @State cachedNarrationTranscripts: string[] = [];
  @State offlineReadOnly: boolean = false;
  @State offlineOwnerId: string = '';
  @State offlineDisplayName: string = '';
  private service: JourneyService = new JourneyService();
  private sosPending: PendingIdempotentOperation = new PendingIdempotentOperation();

  aboutToAppear(): void {
    this.restoreLocalState();
    this.refreshNetworkState();
    if (this.loggedIn) {
      this.loadEmergencyData();
    }
    if (this.loggedIn && this.networkQuality !== NetworkQuality.OFFLINE) {
      this.loadSyncStatus();
      this.loadSosRecords();
    }
  }

  private userId(): string {
    const authenticatedId: string = AuthStore.getInstance().getUserId();
    return authenticatedId.length > 0 ? authenticatedId : this.offlineOwnerId;
  }

  private refreshNetworkState(): void {
    this.networkQuality = NetworkStore.getInstance().getQuality();
    if (this.networkQuality === NetworkQuality.OFFLINE && isOfflineCacheValid(this.cache, this.userId())) {
      this.travelState = this.outbox.items.length > 0 || this.outbox.local_sos !== null ?
        OfflineTravelState.PENDING_SYNC : OfflineTravelState.OFFLINE_CACHE;
    }
  }

  private restoreLocalState(): void {
    if (!this.loggedIn) {
      const profile: OfflineProfile | null = TravelPersistenceStore.getInstance().loadOfflineProfile();
      if (profile === null) { this.travelState = OfflineTravelState.AUTH_REQUIRED; return; }
      this.offlineOwnerId = profile.user_id;
      this.offlineDisplayName = profile.display_name;
      this.offlineReadOnly = true;
    }
    const persistence: TravelPersistenceStore = TravelPersistenceStore.getInstance();
    const packPayload: string = persistence.loadOfflinePack(this.userId());
    if (packPayload.length > 0) {
      try {
        const restored: OfflinePackCache = JSON.parse(packPayload) as OfflinePackCache;
        if (isOfflineCacheValid(restored, this.userId())) {
          this.cache = restored;
          this.travelState = OfflineTravelState.READY;
        } else {
          this.cache = null;
          this.operationMessage = '本地离线包架构、用户或校验信息不匹配，需重新下载';
        }
      } catch (error) {
        this.cache = null;
      }
    }
    this.projectCachedGuidance();
    const queuePayload: string = persistence.loadOfflineQueue(this.userId());
    if (queuePayload.length > 0) {
      try {
        const restoredOutbox: OfflineOutbox = JSON.parse(queuePayload) as OfflineOutbox;
        if (restoredOutbox.schema_version === 1 && restoredOutbox.owner_user_id === this.userId()) {
          this.outbox = restoredOutbox;
        }
      } catch (error) {
        this.outbox = new OfflineOutbox();
      }
    }
    if (this.loggedIn) { this.ensureDeviceIdentity(); }
    if (this.outbox.items.length > 0 || this.outbox.local_sos !== null) {
      this.travelState = OfflineTravelState.PENDING_SYNC;
    }
    this.cachedTicketCount = persistence.loadTicketOrders(this.userId()).length;
    const identity: CachedTicketIdentity | null = persistence.loadTicketIdentity(this.userId());
    this.cachedTicketCode = identity === null ? '' : identity.ticket_code;
    const itinerary: Itinerary | null = persistence.loadItinerary(this.userId());
    this.cachedItineraryName = itinerary === null ? '' : itinerary.name;
    const shopOrders: CachedShopOrder[] = persistence.loadShopOrders(this.userId());
    this.cachedShopOrderCount = shopOrders.length;
    if (this.offlineReadOnly && this.cache !== null && isOfflineCacheValid(this.cache, this.userId())) {
      this.operationMessage = `正在只读查看 ${this.offlineDisplayName} 的用户隔离离线内容；需登录后才能同步或操作`;
    }
  }

  private ensureDeviceIdentity(): void {
    let deviceId: string = this.outbox.device_id;
    if (deviceId.length === 0) {
      deviceId = `harmony-${Date.now().toString()}-${Math.floor(Math.random() * 100000).toString()}`;
    }
    this.outbox.device_id = deviceId;
    this.outbox.owner_user_id = this.userId();
    this.persistOutbox();
  }

  private projectCachedGuidance(): void {
    const guidance: CachedGuidance = extractCachedGuidance(this.cache?.assets ?? []);
    this.cachedEmergencySteps = guidance.emergency_steps;
    this.cachedGuideSections = guidance.guide_sections;
    this.cachedMapNodes = guidance.map_nodes;
    this.cachedNarrationTranscripts = guidance.narration_transcripts;
  }

  private persistCache(): void {
    if (this.cache !== null && this.userId().length > 0) {
      TravelPersistenceStore.getInstance().saveOfflinePack(this.userId(), JSON.stringify(this.cache));
    }
  }

  private persistOutbox(): void {
    if (this.userId().length > 0) {
      this.outbox.owner_user_id = this.userId();
      this.outbox.updated_at = new Date().toISOString();
      TravelPersistenceStore.getInstance().saveOfflineQueue(this.userId(), JSON.stringify(this.outbox));
    }
  }

  private errorText(error: ApiErrorInfo | null): string {
    return error === null ? '离线旅行服务请求失败' : error.userMessage;
  }

  private async downloadPack(): Promise<void> {
    if (!this.loggedIn) {
      this.travelState = OfflineTravelState.AUTH_REQUIRED;
      this.onLoginTap();
      return;
    }
    if (this.operationBusy) { return; }
    this.operationBusy = true;
    this.travelState = OfflineTravelState.DOWNLOADING;
    const packResult: NetworkResult<OfflinePack> = await this.service.latestPack();
    if (!packResult.successful || packResult.data === null) {
      this.operationBusy = false;
      this.handlePackFailure(packResult.error);
      return;
    }
    const pack: OfflinePack = packResult.data;
    const cacheValid: boolean = isOfflineCacheValid(this.cache, this.userId()) && this.cache?.pack.id === pack.id;
    const etag: string = cacheValid ? (this.cache?.manifest.etag ?? '') : '';
    let manifestResult: NetworkResult<OfflineManifest> = await this.service.getManifest(pack.id, etag);
    if (shouldUseCachedManifest(manifestResult.notModified, cacheValid)) {
      this.operationBusy = false;
      this.travelState = OfflineTravelState.READY;
      this.operationMessage = '服务器返回 304，本地缓存校验有效';
      return;
    }
    if (manifestResult.notModified && !cacheValid) {
      this.operationMessage = '304 命中但缓存缺失/损坏，正在无条件重试';
      manifestResult = await this.service.getManifest(pack.id, '');
    }
    if (!manifestResult.successful || manifestResult.data === null) {
      this.operationBusy = false;
      this.handlePackFailure(manifestResult.error);
      return;
    }
    const manifest: OfflineManifest = manifestResult.data;
    const cachedAssets: CachedOfflineAsset[] = [];
    for (let index: number = 0; index < manifest.assets.length; index++) {
      this.operationMessage = `下载 ${index + 1}/${manifest.assets.length}：${manifest.assets[index].title}`;
      const result: NetworkResult<OfflineAssetContent> =
        await this.service.getAsset(pack.id, manifest.assets[index].id);
      if (!result.successful || result.data === null || !assetMatchesManifest(manifest.assets[index], result.data)) {
        this.operationBusy = false;
        this.travelState = OfflineTravelState.FAILED;
        this.operationMessage = `资源 ${manifest.assets[index].title} checksum 不匹配，未覆盖旧缓存`;
        return;
      }
      const asset: CachedOfflineAsset = new CachedOfflineAsset();
      asset.id = result.data.id;
      asset.asset_key = result.data.asset_key;
      asset.kind = result.data.kind;
      asset.title = manifest.assets[index].title;
      asset.content_hash = result.data.content_hash;
      asset.size_bytes = result.data.size_bytes;
      asset.payload_json = JSON.stringify(result.data.payload);
      asset.payload_fingerprint = deterministicPayloadFingerprint(asset.payload_json);
      asset.cached_at = new Date().toISOString();
      cachedAssets.push(asset);
    }
    const next: OfflinePackCache = new OfflinePackCache();
    next.owner_user_id = this.userId();
    next.device_id = this.outbox.device_id;
    next.pack = pack;
    next.manifest = manifest;
    next.manifest_checksum = manifestFingerprint(manifest.pack_id, manifest.version, manifest.etag, manifest.assets);
    next.assets = cachedAssets;
    next.cached_at = new Date().toISOString();
    if (!isOfflineCacheValid(next, this.userId())) {
      this.operationBusy = false;
      this.travelState = OfflineTravelState.FAILED;
      this.operationMessage = '下载完成但本地完整性复核失败';
      return;
    }
    this.cache = next;
    this.projectCachedGuidance();
    this.persistCache();
    this.operationBusy = false;
    this.travelState = this.outbox.items.length > 0 ? OfflineTravelState.PENDING_SYNC : OfflineTravelState.READY;
    this.operationMessage = `离线包 v${pack.version} 已保存，共 ${cachedAssets.length} 项`;
  }

  private handlePackFailure(error: ApiErrorInfo | null): void {
    this.refreshNetworkState();
    if (error !== null && error.code === ApiErrorCode.UNAUTHORIZED) {
      this.travelState = OfflineTravelState.AUTH_REQUIRED;
    } else if (isOfflineCacheValid(this.cache, this.userId())) {
      this.travelState = OfflineTravelState.OFFLINE_CACHE;
      this.operationMessage = '联网失败，继续使用已校验离线缓存';
    } else {
      this.travelState = OfflineTravelState.FAILED;
      this.operationMessage = this.errorText(error);
    }
  }

  private async loadSyncStatus(): Promise<void> {
    if (!this.loggedIn || this.outbox.device_id.length === 0) { return; }
    const result: NetworkResult<SyncStatusResponse> = await this.service.getSyncStatus(this.outbox.device_id);
    if (result.successful && result.data !== null) {
      this.outbox.sync_cursor = this.outbox.sync_cursor ?? result.data.cursor;
      this.outbox.last_client_version = Math.max(this.outbox.last_client_version, result.data.last_client_version);
      this.persistOutbox();
    }
  }

  private nextClientVersion(): number {
    let value: number = this.outbox.last_client_version;
    for (let index: number = 0; index < this.outbox.items.length; index++) {
      value = Math.max(value, this.outbox.items[index].mutation.client_version);
    }
    return value + 1;
  }

  private enqueueMutation(entityType: string, entityId: string, payload: JourneyJsonPayload): void {
    const mutation: OfflineMutation = new OfflineMutation();
    mutation.client_mutation_id = `mutation-${Date.now().toString()}-` +
      `${Math.floor(Math.random() * 100000).toString()}`;
    mutation.client_version = this.nextClientVersion();
    mutation.entity_type = entityType;
    mutation.entity_id = entityId;
    mutation.operation = 'UPSERT';
    mutation.payload = payload;
    if (!isSafeOfflineMutation(mutation)) {
      this.operationMessage = '离线操作不在安全同步白名单中';
      return;
    }
    const item: OfflineOutboxItem = new OfflineOutboxItem();
    item.mutation = mutation;
    item.status = OfflineMutationStatus.PENDING;
    item.created_at = new Date().toISOString();
    const updated: OfflineOutboxItem[] = this.outbox.items.slice();
    updated.push(item);
    this.outbox.items = updated;
    this.persistOutbox();
    this.travelState = OfflineTravelState.PENDING_SYNC;
    this.operationMessage = '操作已先写入 outbox，恢复联网后可幂等同步';
  }

  private queueNote(): void {
    if (!this.loggedIn || this.offlineReadOnly) {
      this.operationMessage = '只读离线身份不能创建 mutation，请重新登录';
      return;
    }
    if (this.noteTitle.trim().length === 0 || this.noteText.trim().length === 0 ||
      this.noteText.trim().length > 2000) {
      this.operationMessage = '请填写标题和 1 至 2000 字便签';
      return;
    }
    this.enqueueMutation('NOTE', `note-${Date.now().toString()}`,
      new NoteMutationPayload(this.noteTitle.trim(), this.noteText.trim()));
    this.noteText = '';
  }

  private queueItineraryAck(): void {
    if (!this.loggedIn || this.offlineReadOnly) {
      this.operationMessage = '只读离线身份不能确认行程，请重新登录';
      return;
    }
    const store: AppStore = AppStore.getInstance();
    if (!store.hasCurrentItinerary()) {
      this.operationMessage = '没有可确认的当前行程';
      return;
    }
    this.enqueueMutation('ITINERARY_ACK', store.getCurrentItineraryId(),
      new ItineraryAckPayload(store.getCurrentItineraryRevision(), new Date().toISOString()));
  }

  private queueEmergencyAck(value: EmergencyBulletin): void {
    if (!this.loggedIn || this.offlineReadOnly) {
      this.operationMessage = '只读离线身份不能写入应急确认';
      return;
    }
    this.enqueueMutation('EMERGENCY_ACK', value.id, new EmergencyAckPayload(value.id));
  }

  private pendingMutations(): OfflineMutation[] {
    const values: OfflineMutation[] = [];
    for (let index: number = 0; index < this.outbox.items.length; index++) {
      if (this.outbox.items[index].status !== OfflineMutationStatus.TERMINAL) {
        values.push(this.outbox.items[index].mutation);
      }
    }
    return values;
  }

  private async syncNow(): Promise<void> {
    if (!this.loggedIn || this.offlineReadOnly) { this.travelState = OfflineTravelState.AUTH_REQUIRED; return; }
    this.refreshNetworkState();
    if (this.networkQuality === NetworkQuality.OFFLINE) {
      this.travelState = OfflineTravelState.PENDING_SYNC;
      this.operationMessage = '仍处于离线状态，outbox 未重放';
      return;
    }
    this.operationBusy = true;
    this.travelState = OfflineTravelState.SYNCING;
    const mutations: OfflineMutation[] = this.pendingMutations();
    let pushResults: SyncPushResult[] = [];
    if (mutations.length > 0) {
      const pushResult: NetworkResult<SyncPushResponse> = await this.service.pushSync(
        this.outbox.device_id, this.outbox.sync_cursor, mutations);
      if (!pushResult.successful || pushResult.data === null) {
        this.operationBusy = false;
        this.handleSyncFailure(pushResult.error);
        return;
      }
      pushResults = pushResult.data.results;
    }
    let cursor: string | null = this.outbox.sync_cursor;
    let pageCount: number = 0;
    let pullComplete: boolean = false;
    while (!pullComplete && pageCount < 20) {
      const pullResult: NetworkResult<SyncPullResponse> = await this.service.pullSync(
        this.outbox.device_id, cursor, 20);
      if (!pullResult.successful || pullResult.data === null) {
        this.operationBusy = false;
        this.handleSyncFailure(pullResult.error);
        return;
      }
      const pageRecords: AppliedSyncRecord[] = [];
      for (let index: number = 0; index < pullResult.data.items.length; index++) {
        const source: SyncMutation = pullResult.data.items[index];
        const record: AppliedSyncRecord = new AppliedSyncRecord();
        record.client_mutation_id = source.client_mutation_id;
        record.entity_type = source.entity_type;
        record.entity_id = source.entity_id;
        record.operation = source.operation;
        record.server_cursor = source.server_cursor;
        record.applied_at = new Date().toISOString();
        pageRecords.push(record);
      }
      const mergedRecords: AppliedSyncRecord[] = mergeAppliedSyncRecords(this.outbox.applied_sync, pageRecords);
      this.outbox.applied_sync = mergedRecords.slice(Math.max(0, mergedRecords.length - 100));
      this.outbox.sync_cursor = pullResult.data.next_cursor;
      cursor = pullResult.data.next_cursor;
      this.persistOutbox();
      pullComplete = !pullResult.data.has_more;
      pageCount += 1;
    }
    if (!pullComplete) {
      this.operationBusy = false;
      this.travelState = OfflineTravelState.FAILED;
      this.operationMessage = '同步超过 20 页安全上限，cursor 停在最后成功落盘页';
      return;
    }
    this.outbox = removeAppliedOutboxItems(this.outbox, pushResults);
    for (let index: number = 0; index < pushResults.length; index++) {
      this.outbox.last_client_version = Math.max(this.outbox.last_client_version, pushResults[index].client_version);
    }
    this.persistOutbox();
    this.operationBusy = false;
    this.travelState = this.outbox.items.length === 0 ? OfflineTravelState.READY : OfflineTravelState.PENDING_SYNC;
    this.operationMessage = `同步完成：push ${pushResults.length} 条，pull cursor 已按页落盘`;
    if (this.outbox.local_sos !== null) {
      this.operationMessage += '；LOCAL_ONLY SOS 仍需手动在线重试';
    }
  }

  private handleSyncFailure(error: ApiErrorInfo | null): void {
    const statusCode: number = error === null ? 0 : error.statusCode;
    const disposition: SyncFailureDisposition = classifySyncFailure(statusCode);
    if (error !== null && (error.serverCode === 'SYNC_CURSOR_INVALID' ||
      error.serverCode === 'SYNC_CURSOR_AHEAD')) {
      this.outbox.sync_cursor = null;
      this.outbox.applied_sync = [];
      this.persistOutbox();
      this.travelState = OfflineTravelState.PENDING_SYNC;
      this.operationMessage = '服务端要求完整重同步；原始 outbox ID/版本/正文已保留，请再次 Push → Pull';
      return;
    }
    if (disposition === SyncFailureDisposition.AUTH_REQUIRED) {
      this.travelState = OfflineTravelState.AUTH_REQUIRED;
      this.operationMessage = '登录失效，outbox 保留且不会跨账号重放';
      return;
    }
    this.outbox = markOutboxFailure(this.outbox, statusCode, this.errorText(error));
    this.persistOutbox();
    this.travelState = disposition === SyncFailureDisposition.RETRYABLE ?
      OfflineTravelState.PENDING_SYNC : OfflineTravelState.FAILED;
    this.operationMessage = disposition === SyncFailureDisposition.RETRYABLE ?
      '0/5xx 可重试；原始 mutation 和版本已保留' : '409/4xx 已标为可见终态，需人工处理';
  }

  private discardTerminalMutations(): void {
    const kept: OfflineOutboxItem[] = [];
    for (let index: number = 0; index < this.outbox.items.length; index++) {
      if (this.outbox.items[index].status !== OfflineMutationStatus.TERMINAL) {
        kept.push(this.outbox.items[index]);
      }
    }
    this.outbox.items = kept;
    this.persistOutbox();
    this.travelState = kept.length > 0 ? OfflineTravelState.PENDING_SYNC : OfflineTravelState.READY;
  }

  private resetSyncCursor(): void {
    this.outbox.sync_cursor = null;
    this.outbox.applied_sync = [];
    this.persistOutbox();
    this.operationMessage = 'cursor 已重置，下次执行用户范围内完整 pull';
  }

  private async loadEmergencyData(): Promise<void> {
    const resourceResult: NetworkResult<EmergencyResourceListResponse> =
      await this.service.listEmergencyResources();
    if (resourceResult.successful && resourceResult.data !== null) {
      this.resources = resourceResult.data.items;
    }
    const bulletinResult: NetworkResult<EmergencyBulletinListResponse> =
      await this.service.listEmergencyBulletins();
    if (bulletinResult.successful && bulletinResult.data !== null) {
      this.bulletins = bulletinResult.data.items;
    }
    this.refreshNetworkState();
  }

  private async loadSosRecords(): Promise<void> {
    const result: NetworkResult<SosListResponse> = await this.service.listSos();
    if (result.successful && result.data !== null) { this.sosRecords = result.data.items; }
  }

  private buildLocalSos(key: string): LocalSosDraft {
    const draft: LocalSosDraft = new LocalSosDraft();
    draft.kind = this.sosKind;
    draft.message = this.sosMessage.trim();
    draft.node_id = this.sosNodeId.trim().length === 0 ? null : this.sosNodeId.trim();
    draft.latitude = this.sosLatitude.trim().length === 0 ? null : Number(this.sosLatitude);
    draft.longitude = this.sosLongitude.trim().length === 0 ? null : Number(this.sosLongitude);
    draft.idempotency_key = key;
    draft.local_status = 'LOCAL_ONLY';
    draft.created_at = new Date().toISOString();
    return draft;
  }

  private async submitSos(): Promise<void> {
    if (!this.loggedIn || this.offlineReadOnly || this.operationBusy) {
      this.travelState = OfflineTravelState.AUTH_REQUIRED;
      return;
    }
    const latitude: number | null = this.sosLatitude.trim().length === 0 ? null : Number(this.sosLatitude);
    const longitude: number | null = this.sosLongitude.trim().length === 0 ? null : Number(this.sosLongitude);
    const validation: JourneyRuleResult = validateSos(this.sosKind, this.sosMessage, latitude, longitude);
    if (!validation.valid) { this.operationMessage = validation.message; return; }
    const operationId: string = `${this.sosKind}:${this.sosMessage.trim()}:${this.sosNodeId}:` +
      `${this.sosLatitude}:${this.sosLongitude}`;
    let key: string = this.sosPending.getOrCreate(operationId, 'demo-sos');
    const cachedDraft: LocalSosDraft | null = this.outbox.local_sos;
    if (cachedDraft !== null && cachedDraft.local_status !== 'TERMINAL' &&
      cachedDraft.idempotency_key.length > 0) {
      key = cachedDraft.idempotency_key;
    }
    this.refreshNetworkState();
    if (this.networkQuality === NetworkQuality.OFFLINE) {
      const localDraft: LocalSosDraft = this.buildLocalSos(key);
      localDraft.local_status = 'PENDING_SYNC';
      this.outbox.local_sos = localDraft;
      this.persistOutbox();
      this.travelState = OfflineTravelState.PENDING_SYNC;
      this.operationMessage = 'LOCAL_ONLY/PENDING_SYNC；未联系、未通知任何真实救援机构';
      return;
    }
    const draft: LocalSosDraft = cachedDraft !== null && cachedDraft.local_status !== 'TERMINAL' ?
      cachedDraft : this.buildLocalSos(key);
    draft.local_status = 'PENDING_SYNC';
    this.outbox.local_sos = draft;
    this.persistOutbox();
    this.operationBusy = true;
    const result: NetworkResult<SosRecord> = await this.service.createSos(
      draft.kind, draft.message, draft.node_id, draft.latitude, draft.longitude, draft.idempotency_key);
    this.operationBusy = false;
    if (result.successful && result.data !== null) {
      this.sosPending.resolveSuccess();
      this.outbox.local_sos = null;
      this.persistOutbox();
      const records: SosRecord[] = this.sosRecords.slice();
      records.unshift(result.data);
      this.sosRecords = records;
      this.operationMessage = `${result.data.status} · real_dispatch=${result.data.real_dispatch} · ` +
        `${result.data.disclaimer}`;
    } else {
      if (result.error !== null && result.error.code === ApiErrorCode.OFFLINE) {
        draft.local_status = 'PENDING_SYNC';
        this.outbox.local_sos = draft;
        this.persistOutbox();
        this.travelState = OfflineTravelState.PENDING_SYNC;
        this.operationMessage = '网络探测后确认离线：SOS 仅 LOCAL_ONLY/PENDING_SYNC，未通知真实救援';
        return;
      }
      if (result.error !== null) { this.sosPending.resolveFailure(result.error.statusCode, result.error.retriable); }
      if (this.outbox.local_sos !== null) {
        this.outbox.local_sos.local_status = result.error !== null && result.error.retriable ?
          'PENDING_SYNC' : 'TERMINAL';
        this.persistOutbox();
      }
      this.operationMessage = this.errorText(result.error);
    }
  }

  private useDemoLocation(): void {
    this.sosLatitude = '30.2741';
    this.sosLongitude = '120.1551';
    this.operationMessage = '固定定位演示；未调用真实定位硬件';
  }

  @Builder
  private stateBanner() {
    Row() {
      Column({ space: 2 }) {
        Text(`${offlineStateLabel(this.travelState)} · 网络 ${this.networkQuality}`).fontWeight(FontWeight.Bold)
          .fontColor(this.networkQuality === NetworkQuality.OFFLINE ? $r('app.color.warning') :
            $r('app.color.primary'))
        Text(`outbox ${this.outbox.items.length} 条 · cursor ${this.outbox.sync_cursor ?? 'null'}`).fontSize(8)
          .fontColor($r('app.color.text_secondary'))
      }.alignItems(HorizontalAlign.Start).layoutWeight(1)
      Button('刷新网络').fontSize(9).onClick(() => { this.refreshNetworkState(); })
    }.width('100%').padding(11).borderRadius(12).backgroundColor($r('app.color.surface_tint'))
  }

  @Builder
  private packPanel() {
    Column({ space: 8 }) {
      Text('弱网离线旅行包').width('100%').fontSize(17).fontWeight(FontWeight.Bold)
        .fontColor($r('app.color.text_primary'))
      Text('票据身份、地图、行程、讲解与应急指引；短期扫码 bearer 不落盘。').width('100%')
        .fontSize(9).fontColor($r('app.color.warning'))
      if (this.cache !== null && isOfflineCacheValid(this.cache, this.userId())) {
        Text(`${this.cache.pack.name} v${this.cache.pack.version} · ${this.cache.assets.length} 项 · ` +
          `${this.cache.pack.total_size_bytes} bytes`).width('100%').fontColor($r('app.color.primary'))
        Text(`ETag ${this.cache.manifest.etag} · schema ${this.cache.schema_version} · checksum scoped`)
          .width('100%').fontSize(8).fontColor($r('app.color.text_secondary'))
        ForEach(this.cache.assets, (asset: CachedOfflineAsset) => {
          Text(`${asset.kind} · ${asset.title} · ${asset.size_bytes} bytes`).width('100%').padding(8)
            .fontSize(9).fontColor($r('app.color.text_primary')).backgroundColor($r('app.color.surface_tint'))
            .borderRadius(9)
        }, (asset: CachedOfflineAsset) => asset.id)
      } else if (this.travelState === OfflineTravelState.NO_PACK) {
        StatePanel({ state: ContentState.EMPTY, message: '尚未下载离线包' })
      }
      if (this.loggedIn) {
        Button(this.operationBusy ? '处理中…' : (this.cache === null ? '下载离线包' : '检查并更新'))
          .enabled(!this.operationBusy).width('100%').fontColor(Color.White)
          .backgroundColor($r('app.color.primary')).onClick(() => { this.downloadPack(); })
      }
      Column({ space: 3 }) {
        Text('本地安全快照').width('100%').fontWeight(FontWeight.Medium).fontColor($r('app.color.text_primary'))
        Text(`门票订单 ${this.cachedTicketCount} · 非扫码票据 ${this.cachedTicketCode || '无'} · ` +
          `行程 ${this.cachedItineraryName || '无'} · 商城订单 ${this.cachedShopOrderCount}`)
          .width('100%').fontSize(9).fontColor($r('app.color.text_secondary'))
      }.width('100%').padding(9).borderRadius(10).backgroundColor($r('app.color.surface_tint'))
      if (this.cachedGuideSections.length > 0 || this.cachedMapNodes.length > 0 ||
        this.cachedNarrationTranscripts.length > 0) {
        Column({ space: 3 }) {
          Text('进程重启后可见的离线核心内容').width('100%').fontWeight(FontWeight.Medium)
            .fontColor($r('app.color.text_primary'))
          ForEach(this.cachedGuideSections, (value: string) => {
            Text(`指南 · ${value}`).width('100%').fontSize(8).fontColor($r('app.color.primary'))
          }, (value: string) => value)
          ForEach(this.cachedMapNodes, (value: string) => {
            Text(`地图节点 · ${value}`).width('100%').fontSize(8).fontColor($r('app.color.text_secondary'))
          }, (value: string) => value)
          ForEach(this.cachedNarrationTranscripts, (value: string) => {
            Text(`离线讲解 · ${value}`).width('100%').fontSize(8).fontColor($r('app.color.primary'))
          }, (value: string) => value)
        }.width('100%').padding(8).borderRadius(9).backgroundColor($r('app.color.surface_tint'))
      }
    }.width('100%').padding(13).borderRadius(16).backgroundColor($r('app.color.surface'))
  }

  @Builder
  private outboxPanel() {
    Column({ space: 7 }) {
      Text('安全离线 outbox').width('100%').fontSize(17).fontWeight(FontWeight.Bold)
        .fontColor($r('app.color.text_primary'))
      TextInput({ text: this.noteTitle, placeholder: '便签标题' }).width('100%')
        .onChange((value: string) => { this.noteTitle = value; })
      TextArea({ text: this.noteText, placeholder: '离线便签内容' }).width('100%').height(70)
        .onChange((value: string) => { this.noteText = value; })
      Row({ space: 6 }) {
        Button('先落盘便签').layoutWeight(1).onClick(() => { this.queueNote(); })
        Button('确认查看当前行程').layoutWeight(1).onClick(() => { this.queueItineraryAck(); })
      }.width('100%')
      ForEach(this.outbox.items, (item: OfflineOutboxItem) => {
        Column({ space: 2 }) {
          Text(`${item.mutation.client_version} · ${item.mutation.entity_type} · ${item.status}`).width('100%')
            .fontSize(9).fontColor(item.status === OfflineMutationStatus.TERMINAL ?
              $r('app.color.error') : $r('app.color.primary'))
          if (item.error_message.length > 0) {
            Text(item.error_message).width('100%').fontSize(8).fontColor($r('app.color.warning'))
          }
        }.width('100%').padding(7).borderRadius(8).backgroundColor($r('app.color.surface_tint'))
      }, (item: OfflineOutboxItem) => item.mutation.client_mutation_id)
      Row({ space: 5 }) {
        Button(this.operationBusy ? '同步中…' : 'Push → Pull').enabled(!this.operationBusy)
          .layoutWeight(1).fontColor(Color.White).backgroundColor($r('app.color.primary'))
          .onClick(() => { this.syncNow(); })
        Button('重置 cursor').fontSize(8).onClick(() => { this.resetSyncCursor(); })
        Button('丢弃终态').fontSize(8).fontColor($r('app.color.error'))
          .onClick(() => { this.discardTerminalMutations(); })
      }.width('100%')
    }.width('100%').padding(13).borderRadius(16).backgroundColor($r('app.color.surface'))
  }

  @Builder
  private emergencyPanel() {
    Column({ space: 8 }) {
      Text('应急助手（DEMO）').width('100%').fontSize(17).fontWeight(FontWeight.Bold)
        .fontColor($r('app.color.error'))
      Text('curated_demo 指引；SOS 仅持久化留痕，绝不表示真实救援已派遣。').width('100%')
        .fontSize(9).fontColor($r('app.color.warning'))
      if (this.cachedEmergencySteps.length > 0) {
        Column({ space: 3 }) {
          Text('离线疏散指引（已从持久化资源恢复）').width('100%').fontWeight(FontWeight.Medium)
            .fontColor($r('app.color.error'))
          ForEach(this.cachedEmergencySteps, (step: string, index: number) => {
            Text(`${index + 1}. ${step}`).width('100%').fontSize(9).fontColor($r('app.color.text_primary'))
          }, (step: string, index: number) => `${index}:${step}`)
        }.width('100%').padding(9).borderRadius(10).backgroundColor($r('app.color.surface_tint'))
      }
      ForEach(this.bulletins, (bulletin: EmergencyBulletin) => {
        Column({ space: 3 }) {
          Text(`[${bulletin.severity}] ${bulletin.title}`).width('100%').fontWeight(FontWeight.Medium)
            .fontColor(bulletin.severity === 'CRITICAL' ? $r('app.color.error') : $r('app.color.warning'))
          Text(bulletin.content).width('100%').fontSize(9).fontColor($r('app.color.text_secondary'))
          if (this.loggedIn) {
            Button('离线确认已读').fontSize(8).onClick(() => { this.queueEmergencyAck(bulletin); })
          }
        }.width('100%').padding(9).borderRadius(10).backgroundColor($r('app.color.surface_tint'))
      }, (bulletin: EmergencyBulletin) => bulletin.id)
      ForEach(this.resources, (resource: EmergencyResource) => {
        Column({ space: 3 }) {
          Text(`${resource.kind} · ${resource.title}`).width('100%').fontWeight(FontWeight.Medium)
            .fontColor($r('app.color.text_primary'))
          Text(resource.description).width('100%').fontSize(9).fontColor($r('app.color.text_secondary'))
          Text(resource.instructions.join(' → ')).width('100%').fontSize(8).fontColor($r('app.color.primary'))
          Text(`provider=${resource.provider}/demo=${resource.is_demo}`).width('100%').fontSize(7)
            .fontColor($r('app.color.warning'))
        }.width('100%').padding(9).borderRadius(10).backgroundColor($r('app.color.surface'))
      }, (resource: EmergencyResource) => resource.id)
      if (this.loggedIn) {
        Row({ space: 4 }) {
          Button('医疗').layoutWeight(1).onClick(() => { this.sosKind = 'MEDICAL'; })
          Button('走失').layoutWeight(1).onClick(() => { this.sosKind = 'LOST'; })
          Button('安全').layoutWeight(1).onClick(() => { this.sosKind = 'SAFETY'; })
          Button('其他').layoutWeight(1).onClick(() => { this.sosKind = 'OTHER'; })
        }.width('100%')
        TextArea({ text: this.sosMessage, placeholder: '演示求助说明' }).width('100%').height(65)
          .onChange((value: string) => { this.sosMessage = value; })
        TextInput({ text: this.sosNodeId, placeholder: '节点 UUID（选填）' }).width('100%')
          .onChange((value: string) => { this.sosNodeId = value; })
        Row({ space: 5 }) {
          TextInput({ text: this.sosLatitude, placeholder: '纬度' }).layoutWeight(1)
            .onChange((value: string) => { this.sosLatitude = value; })
          TextInput({ text: this.sosLongitude, placeholder: '经度' }).layoutWeight(1)
            .onChange((value: string) => { this.sosLongitude = value; })
          Button('定位演示').fontSize(8).onClick(() => { this.useDemoLocation(); })
        }.width('100%')
        Button(this.operationBusy ? '处理中…' : '提交/重试演示 SOS').enabled(!this.operationBusy).width('100%')
          .fontColor(Color.White).backgroundColor($r('app.color.error')).onClick(() => { this.submitSos(); })
      }
      if (this.outbox.local_sos !== null) {
        Text(`${this.outbox.local_sos.local_status} · 未通知真实救援 · ${this.outbox.local_sos.message}`)
          .width('100%').padding(8).fontSize(9).fontColor($r('app.color.error'))
          .backgroundColor($r('app.color.surface_tint')).borderRadius(9)
      }
      ForEach(this.sosRecords, (record: SosRecord) => {
        Text(`${record.sos_no} · ${record.status} · real_dispatch=${record.real_dispatch} · ${record.disclaimer}`)
          .width('100%').padding(8).fontSize(8).fontColor($r('app.color.warning'))
          .backgroundColor($r('app.color.surface')).borderRadius(9)
      }, (record: SosRecord) => record.id)
    }.width('100%').padding(13).borderRadius(16).backgroundColor($r('app.color.surface'))
  }

  build() {
    Column({ space: 10 }) {
      Text('离线旅行包与应急助手').width('100%').fontSize(19).fontWeight(FontWeight.Bold)
        .fontColor($r('app.color.text_primary'))
      this.stateBanner()
      if (!this.loggedIn && !this.offlineReadOnly) {
        StatePanel({ state: ContentState.NO_PERMISSION, message: '登录后下载用户隔离离线包并管理 outbox' })
        Button('立即登录').width('100%').fontColor(Color.White).backgroundColor($r('app.color.primary'))
          .onClick(() => { this.onLoginTap(); })
      } else if (this.offlineReadOnly) {
        Text(`只读离线身份：${this.offlineDisplayName} · 不执行网络、同步或 mutation`).width('100%')
          .padding(9).fontSize(9).fontColor($r('app.color.warning'))
          .backgroundColor($r('app.color.surface_tint')).borderRadius(10)
        if (this.isWide) {
          Row({ space: 12 }) {
            Column() { this.packPanel() }.layoutWeight(1)
            Column() { this.emergencyPanel() }.layoutWeight(1)
          }.width('100%').alignItems(VerticalAlign.Top)
        } else {
          this.packPanel()
          this.emergencyPanel()
        }
      } else if (this.isWide) {
        Row({ space: 12 }) {
          Column({ space: 10 }) { this.packPanel(); this.outboxPanel() }.layoutWeight(1)
          Column() { this.emergencyPanel() }.layoutWeight(1)
        }.width('100%').alignItems(VerticalAlign.Top)
      } else {
        this.packPanel()
        this.outboxPanel()
        this.emergencyPanel()
      }
      if (this.operationMessage.length > 0) {
        Text(this.operationMessage).width('100%').padding(9).borderRadius(10).fontSize(9)
          .fontColor($r('app.color.warning')).backgroundColor($r('app.color.surface_tint'))
      }
    }.width('100%').onAreaChange((_oldArea: Area, newArea: Area) => {
      this.isWide = isWideWindow(Number(newArea.width));
    })
  }
}
