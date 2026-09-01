import { describe, expect, it } from '@ohos/hypium';
import { TripPlanItem } from '../main/ets/models/AppModels';
import {
  ExperienceSession,
  QueueStatus,
  Reservation,
  ReservationAllocation,
  ReservationStatus,
  SessionStatus
} from '../main/ets/models/BookingModels';
import {
  CrowdLevel,
  Itinerary,
  ItineraryGenerateRequest,
  ItineraryItem
} from '../main/ets/models/GuideModels';
import { TicketOrderStatus, TicketQrResponse, TicketSlot } from '../main/ets/models/TicketModels';
import { CartItem, PointsReward, ShopOrder, ShopOrderItem, ShopOrderStatus, ShopProduct } from '../main/ets/models/ShopModels';
import { FeedbackKind, FacilityItem } from '../main/ets/models/ServiceModels';
import {
  CachedOfflineAsset,
  AppliedSyncRecord,
  CachedGuidance,
  JourneyJsonPayload,
  OfflineAssetContent,
  OfflineAssetManifest,
  OfflineMutation,
  OfflineMutationStatus,
  OfflineOutbox,
  OfflineOutboxItem,
  OfflinePackCache,
  OfflineTravelState,
  SyncPushResult
} from '../main/ets/models/JourneyModels';
import {
  CachedShopOrder,
  CachedTicketIdentity,
  createOwnedCacheEnvelope,
  deterministicPayloadFingerprint,
  isSafeTravelCachePayload,
  readOwnedCacheEnvelope
} from '../main/ets/models/PersistenceModels';
import { ApiErrorCode, ApiErrorInfo, extractServerErrorCode, mapApiError } from '../main/ets/network/ApiError';
import { NetworkResult } from '../main/ets/network/HttpClient';
import { JourneyRoutePolicy } from '../main/ets/network/services/JourneyService';
import { ValidationResult, validateCredentials, validatePassword, validatePhone } from '../main/ets/utils/InputValidators';
import { findTripConflict, hasTripConflict } from '../main/ets/utils/TripConflict';
import { globalContentExtent, globalContentScale } from '../main/ets/utils/AccessibilityRules';
import { WindowSizeClass, classifyWindowWidth, isWideWindow } from '../main/ets/utils/ResponsiveRules';
import {
  detectSessionInventoryChange,
  hasReservationConflict,
  isCurrentItinerarySuggestion,
  isTerminalQueueStatus,
  parseQueueEvent,
  shanghaiDateAfterDays,
  shouldAcceptQueueEvent,
  shouldAcceptQueueSequence,
  validateBookingDate,
  validateReview,
  validateSessionReservation,
  validateStayBooking,
  validateTimedBooking
} from '../main/ets/utils/BookingRules';
import {
  assessReplan,
  classifyCrowdLevel,
  findTimelineConflict,
  parseCrowdEnvelope,
  shouldAcceptCrowdSequence,
  validateItineraryGenerateInput
} from '../main/ets/utils/GuideRules';
import {
  TicketOrderAction,
  PendingIdempotentOperation,
  canApplyTicketAction,
  detectInventoryChange,
  transitionTicketOrderStatus,
  validateTicketQuantity,
  validateVisitDate
} from '../main/ets/utils/TicketRules';
import {
  canPayShopOrder,
  effectiveProductPrice,
  validateCartQuantity,
  validateCheckout,
  validateRewardRedemption,
  validateShare
} from '../main/ets/utils/ShopRules';
import {
  facilityMatchesPreference,
  parseSupportEvent,
  shouldAcceptSupportSequence,
  validateFeedback,
  validateFollowUp,
  validateInviteCode,
  validateMeetingPoint,
  validateMemberStatus,
  validateSupportMessage
} from '../main/ets/utils/ServiceRules';
import {
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
  validateGreenEvidence,
  validateSos
} from '../main/ets/utils/JourneyRules';

export default function tourismBusinessRulesTest() {
  describe('tourismBusinessRules', () => {
    it('mapsAuthenticationAndServerErrors', 0, () => {
      const unauthorized: ApiErrorInfo = mapApiError(401, '', false);
      const unavailable: ApiErrorInfo = mapApiError(503, '', false);
      const offline: ApiErrorInfo = mapApiError(0, '', true);

      expect(unauthorized.code).assertEqual(ApiErrorCode.UNAUTHORIZED);
      expect(unauthorized.retriable).assertFalse();
      expect(unavailable.code).assertEqual(ApiErrorCode.SERVER);
      expect(unavailable.retriable).assertTrue();
      expect(offline.code).assertEqual(ApiErrorCode.OFFLINE);
    });

    it('mapsTimeoutBeforeUnknownError', 0, () => {
      const timeout: ApiErrorInfo = mapApiError(0, 'socket timed out', false);
      expect(timeout.code).assertEqual(ApiErrorCode.TIMEOUT);
      expect(timeout.retriable).assertTrue();
    });

    it('validatesLoginInputs', 0, () => {
      const phone: ValidationResult = validatePhone('13800138000');
      const invalidPhone: ValidationResult = validatePhone('12345');
      const password: ValidationResult = validatePassword('secret123');
      const credentials: ValidationResult = validateCredentials('tourist', 'secret123');

      expect(phone.valid).assertTrue();
      expect(invalidPhone.valid).assertFalse();
      expect(password.valid).assertTrue();
      expect(credentials.valid).assertTrue();
    });

    it('detectsOverlappingTripItems', 0, () => {
      const items: TripPlanItem[] = [
        new TripPlanItem('a', '文化馆', '2026-09-01T09:00', '2026-09-01T10:00', '文化区'),
        new TripPlanItem('b', '演出', '2026-09-01T09:45', '2026-09-01T10:30', '剧场')
      ];

      expect(hasTripConflict(items)).assertTrue();
      expect(findTripConflict(items).firstItemId).assertEqual('a');
      expect(findTripConflict(items).secondItemId).assertEqual('b');
    });

    it('allowsAdjacentTripItems', 0, () => {
      const items: TripPlanItem[] = [
        new TripPlanItem('later', '午餐', '2026-09-01T11:00', '2026-09-01T12:00', '餐厅'),
        new TripPlanItem('first', '演出', '2026-09-01T10:00', '2026-09-01T11:00', '剧场')
      ];

      expect(hasTripConflict(items)).assertFalse();
    });

    it('validatesTicketBookingInput', 0, () => {
      expect(validateVisitDate('2026-09-01').valid).assertTrue();
      expect(validateVisitDate('2026-02-30').valid).assertFalse();
      expect(validateTicketQuantity(2, 5).valid).assertTrue();
      expect(validateTicketQuantity(0, 5).valid).assertFalse();
      expect(validateTicketQuantity(6, 5).valid).assertFalse();
    });

    it('enforcesTicketOrderStateMachine', 0, () => {
      expect(canApplyTicketAction(TicketOrderStatus.PENDING_PAYMENT, TicketOrderAction.PAY)).assertTrue();
      expect(transitionTicketOrderStatus(TicketOrderStatus.PENDING_PAYMENT, TicketOrderAction.PAY))
        .assertEqual(TicketOrderStatus.PAID);
      expect(canApplyTicketAction(TicketOrderStatus.PAID, TicketOrderAction.REFUND)).assertTrue();
      expect(transitionTicketOrderStatus(TicketOrderStatus.PAID, TicketOrderAction.REFUND))
        .assertEqual(TicketOrderStatus.REFUNDED);
      expect(canApplyTicketAction(TicketOrderStatus.REFUNDED, TicketOrderAction.PAY)).assertFalse();
    });

    it('detectsTicketInventoryAndPriceChanges', 0, () => {
      const before: TicketSlot = new TicketSlot();
      before.id = 'slot-1';
      before.remaining = 8;
      before.unit_price_cents = 10000;
      const after: TicketSlot = new TicketSlot();
      after.id = 'slot-1';
      after.remaining = 3;
      after.unit_price_cents = 12000;

      expect(detectInventoryChange(before, after).changed).assertTrue();
      expect(detectInventoryChange(before, after).priceChanged).assertTrue();
      after.remaining = 0;
      expect(detectInventoryChange(before, after).depleted).assertTrue();
    });

    it('reusesIdempotencyKeyUntilOperationSettles', 0, () => {
      const pending: PendingIdempotentOperation = new PendingIdempotentOperation();
      const firstKey: string = pending.getOrCreate('slot-1:2', 'ticket-order');
      pending.resolveFailure(0, true);
      expect(pending.getOrCreate('slot-1:2', 'ticket-order')).assertEqual(firstKey);
      pending.resolveFailure(503, true);
      expect(pending.getOrCreate('slot-1:2', 'ticket-order')).assertEqual(firstKey);
      pending.resolveFailure(409, false);
      expect(pending.getOperationId()).assertEqual('');
      expect(pending.getKey()).assertEqual('');
    });

    it('classifiesCrowdAndRejectsStaleSequence', 0, () => {
      expect(classifyCrowdLevel(2000, 5)).assertEqual(CrowdLevel.LOW);
      expect(classifyCrowdLevel(5000, 8)).assertEqual(CrowdLevel.MEDIUM);
      expect(classifyCrowdLevel(3000, 45)).assertEqual(CrowdLevel.HIGH);
      expect(shouldAcceptCrowdSequence(8, 9)).assertTrue();
      expect(shouldAcceptCrowdSequence(9, 9)).assertFalse();
      expect(shouldAcceptCrowdSequence(9, 8)).assertFalse();
    });

    it('parsesUnifiedCrowdWebSocketEnvelope', 0, () => {
      const payload: string = '{"id":"event-1","type":"crowd.snapshot","occurred_at":"2026-09-01T10:00:00Z",' +
        '"data":{"items":[{"attraction_id":"a1","captured_at":"2026-09-01T10:00:00Z",' +
        '"people_count":12,"occupancy_bps":3000,"level":"LOW","wait_minutes":5,"source":"simulated"}],' +
        '"sequence":7,"captured_at":"2026-09-01T10:00:00Z","source":"simulated","is_demo":true}}';
      expect(parseCrowdEnvelope(payload).valid).assertTrue();
      expect(parseCrowdEnvelope('{bad json').valid).assertFalse();
      expect(parseCrowdEnvelope(payload).envelope === null).assertFalse();
      if (parseCrowdEnvelope(payload).envelope !== null) {
        expect(parseCrowdEnvelope(payload).envelope?.data.sequence).assertEqual(7);
      }
    });

    it('validatesItineraryGenerationInput', 0, () => {
      const input: ItineraryGenerateRequest = new ItineraryGenerateRequest();
      input.visit_date = '2026-09-02';
      input.start_time = '09:00';
      input.duration_minutes = 360;
      input.interests = ['culture'];
      input.companion_type = 'family';
      input.fitness_level = 'medium';
      expect(validateItineraryGenerateInput(input).valid).assertTrue();
      input.duration_minutes = 30;
      expect(validateItineraryGenerateInput(input).valid).assertFalse();
      input.duration_minutes = 360;
      input.interests = [];
      expect(validateItineraryGenerateInput(input).valid).assertFalse();
    });

    it('showsTimelineOverlapConflict', 0, () => {
      const first: ItineraryItem = new ItineraryItem();
      first.id = 'first';
      first.title = '文化馆';
      first.start_at = '2026-09-02T09:00:00';
      first.end_at = '2026-09-02T10:00:00';
      const second: ItineraryItem = new ItineraryItem();
      second.id = 'second';
      second.title = '演出';
      second.start_at = '2026-09-02T09:45:00';
      second.end_at = '2026-09-02T10:30:00';
      expect(findTimelineConflict([first, second]).conflicted).assertTrue();
      second.start_at = '2026-09-02T10:00:00';
      expect(findTimelineConflict([first, second]).conflicted).assertFalse();
    });

    it('acceptsReplanOnlyWhenLockedItemsStayFixed', 0, () => {
      const lockedBefore: ItineraryItem = new ItineraryItem();
      lockedBefore.id = 'ticket';
      lockedBefore.ref_id = 'ticket-order';
      lockedBefore.title = '锁定入园预约';
      lockedBefore.start_at = '2026-09-02T09:00:00';
      lockedBefore.end_at = '2026-09-02T09:20:00';
      lockedBefore.locked = true;
      const previous: Itinerary = new Itinerary();
      previous.id = 'trip-1';
      previous.revision = 1;
      previous.items = [lockedBefore];
      const lockedAfter: ItineraryItem = new ItineraryItem();
      lockedAfter.id = 'ticket';
      lockedAfter.ref_id = 'ticket-order';
      lockedAfter.title = '锁定入园预约';
      lockedAfter.start_at = '2026-09-02T09:00:00';
      lockedAfter.end_at = '2026-09-02T09:20:00';
      lockedAfter.locked = true;
      const updated: Itinerary = new Itinerary();
      updated.id = 'trip-1';
      updated.revision = 2;
      updated.items = [lockedAfter];
      expect(assessReplan(previous, updated).accepted).assertTrue();
      lockedAfter.start_at = '2026-09-02T09:10:00';
      expect(assessReplan(previous, updated).accepted).assertFalse();
    });

    it('validatesExperienceDateCapacityAndInventory', 0, () => {
      const session: ExperienceSession = new ExperienceSession();
      session.id = 'session-1';
      session.status = SessionStatus.OPEN;
      session.remaining = 4;
      expect(validateBookingDate('2026-09-02').valid).assertTrue();
      expect(validateBookingDate('2026-02-30').valid).assertFalse();
      expect(validateSessionReservation(session, 3).valid).assertTrue();
      expect(validateSessionReservation(session, 5).valid).assertFalse();
      const updated: ExperienceSession = new ExperienceSession();
      updated.id = 'session-1';
      updated.status = SessionStatus.OPEN;
      updated.remaining = 0;
      expect(detectSessionInventoryChange(session, updated).depleted).assertTrue();
    });

    it('usesAsiaShanghaiBusinessDates', 0, () => {
      const utcLateAfternoon: number = Date.UTC(2026, 8, 1, 16, 30, 0);
      expect(shanghaiDateAfterDays(0, utcLateAfternoon)).assertEqual('2026-09-02');
      expect(shanghaiDateAfterDays(1, utcLateAfternoon)).assertEqual('2026-09-03');
    });

    it('validatesHospitalityAndReviewInputs', 0, () => {
      expect(validateStayBooking('2026-09-02', '2026-09-04', 1, 2).valid).assertTrue();
      expect(validateStayBooking('2026-09-04', '2026-09-02', 1, 2).valid).assertFalse();
      expect(validateTimedBooking('2026-09-02T18:00:00+08:00', 4).valid).assertTrue();
      expect(validateReview(5, '服务体验很好').valid).assertTrue();
      expect(validateReview(0, '服务体验很好').valid).assertFalse();
    });

    it('detectsReservationAllocationConflict', 0, () => {
      const allocation: ReservationAllocation = new ReservationAllocation();
      allocation.starts_at = '2026-09-02T10:00:00';
      allocation.ends_at = '2026-09-02T11:00:00';
      const reservation: Reservation = new Reservation();
      reservation.status = ReservationStatus.CONFIRMED;
      reservation.allocations = [allocation];
      expect(hasReservationConflict([reservation], '2026-09-02T10:30:00', '2026-09-02T11:30:00')).assertTrue();
      expect(hasReservationConflict([reservation], '2026-09-02T11:00:00', '2026-09-02T12:00:00')).assertFalse();
    });

    it('parsesQueueEventAndRejectsStaleSequence', 0, () => {
      const payload: string = '{"id":"queue-event-1","type":"queue.updated","occurred_at":"2026-09-01T10:00:00Z",' +
        '"data":{"queue":{"id":"queue-1","queue_no":"Q001","experience_id":"ride-1",' +
        '"experience_name":"飞行项目","status":"WAITING","party_size":2,"estimated_wait_minutes":20,' +
        '"sequence":4,"joined_at":"2026-09-01T09:50:00Z","called_at":null,"itinerary_id":null,' +
        '"itinerary_revision":null,"nearby_recommendations":[],"fast_pass":null},' +
        '"source":"simulated","is_demo":true,"recommendation":null,"itinerary_id":null,' +
        '"itinerary_revision":null}}';
      expect(parseQueueEvent(payload).valid).assertTrue();
      expect(parseQueueEvent('{broken').valid).assertFalse();
      expect(shouldAcceptQueueSequence(3, 4)).assertTrue();
      expect(shouldAcceptQueueSequence(4, 4)).assertFalse();
      expect(shouldAcceptQueueEvent(4, 4, 'nearby.recommended')).assertTrue();
      expect(shouldAcceptQueueEvent(4, 4, 'itinerary.replan_available')).assertTrue();
      expect(shouldAcceptQueueEvent(4, 4, 'queue.updated')).assertFalse();
      expect(shouldAcceptQueueEvent(4, 3, 'nearby.recommended')).assertFalse();
      const event = parseQueueEvent(payload).envelope;
      if (event !== null) {
        expect(event.data.queue.status).assertEqual(QueueStatus.WAITING);
      }
    });

    it('rejectsStaleQueueItinerarySuggestion', 0, () => {
      expect(isCurrentItinerarySuggestion('trip-1', 3, 'trip-1', 3)).assertTrue();
      expect(isCurrentItinerarySuggestion('trip-1', 3, 'trip-1', 2)).assertFalse();
      expect(isCurrentItinerarySuggestion('trip-1', 3, 'trip-2', 3)).assertFalse();
      expect(isCurrentItinerarySuggestion('trip-1', 3, null, null)).assertFalse();
    });

    it('recognizesQueueTerminalStates', 0, () => {
      expect(isTerminalQueueStatus(QueueStatus.COMPLETED)).assertTrue();
      expect(isTerminalQueueStatus(QueueStatus.LEFT)).assertTrue();
      expect(isTerminalQueueStatus(QueueStatus.EXPIRED)).assertTrue();
      expect(isTerminalQueueStatus(QueueStatus.WAITING)).assertFalse();
      expect(isTerminalQueueStatus(QueueStatus.CALLED)).assertFalse();
    });

    it('reusesQueueJoinIdempotencyKeyAfterNetworkFailure', 0, () => {
      const pending: PendingIdempotentOperation = new PendingIdempotentOperation();
      const firstKey: string = pending.getOrCreate('ride-1:2:trip-1', 'queue-join');
      pending.resolveFailure(0, true);
      expect(pending.getOrCreate('ride-1:2:trip-1', 'queue-join')).assertEqual(firstKey);
      pending.resolveFailure(409, false);
      expect(pending.getKey()).assertEqual('');
    });

    it('appliesCampaignPriceAndCartInventoryRules', 0, () => {
      const product: ShopProduct = new ShopProduct();
      product.price_cents = 10000;
      product.effective_price_cents = 8000;
      product.stock = 3;
      expect(effectiveProductPrice(product)).assertEqual(8000);
      expect(validateCartQuantity(3, product.stock).valid).assertTrue();
      expect(validateCartQuantity(4, product.stock).valid).assertFalse();
      product.effective_price_cents = 12000;
      expect(effectiveProductPrice(product)).assertEqual(10000);
    });

    it('validatesServerAuthoritativeCheckoutAndTerminalOrders', 0, () => {
      const item: CartItem = new CartItem();
      item.quantity = 2;
      item.stock = 5;
      expect(validateCheckout([item], '游客', '13800138000', '浙江省', '杭州市', '游客中心自提点').valid)
        .assertTrue();
      expect(validateCheckout([], '游客', '13800138000', '浙江省', '杭州市', '游客中心自提点').valid)
        .assertFalse();
      expect(canPayShopOrder(ShopOrderStatus.PENDING_PAYMENT)).assertTrue();
      expect(canPayShopOrder(ShopOrderStatus.EXPIRED)).assertFalse();
      expect(canPayShopOrder(ShopOrderStatus.PAID)).assertFalse();
    });

    it('validatesPointsRedeemAndDemoShare', 0, () => {
      const reward: PointsReward = new PointsReward();
      reward.points_cost = 300;
      reward.stock = 2;
      expect(validateRewardRedemption(500, reward).valid).assertTrue();
      expect(validateRewardRedemption(200, reward).valid).assertFalse();
      expect(validateShare('PRODUCT', 'product-1', '分享景区好物').valid).assertTrue();
      expect(validateShare('PRODUCT', '', '分享景区好物').valid).assertFalse();
    });

    it('validatesFeedbackSupportAndGroupInputs', 0, () => {
      expect(validateFeedback(FeedbackKind.COMPLAINT, '排队体验', '等待时间过长').valid).assertTrue();
      expect(validateFollowUp(5, '处理及时').valid).assertTrue();
      expect(validateSupportMessage('请问集合点在哪里').valid).assertTrue();
      expect(validateInviteCode('ABC123').valid).assertTrue();
      expect(validateInviteCode('bad').valid).assertFalse();
      expect(validateMeetingPoint('游客中心', '').valid).assertTrue();
      expect(validateMemberStatus('LOST', '正在原地等待').valid).assertTrue();
      expect(validateMemberStatus('UNKNOWN', '').valid).assertFalse();
    });

    it('ordersAndParsesSupportWebSocketMessages', 0, () => {
      const payload: string = '{"id":"support-event-1","type":"support.message",' +
        '"occurred_at":"2026-09-01T12:00:00Z","data":{"conversation":{"id":"conversation-1",' +
        '"subject":"咨询","status":"OPEN","provider":"demo_support_bot","is_demo":true,' +
        '"last_message_at":"2026-09-01T12:00:00Z","created_at":"2026-09-01T11:00:00Z"},' +
        '"message":{"id":"message-1","conversation_id":"conversation-1","sender_type":"BOT",' +
        '"sender_name":"DemoSupportBot","content":"您好","sequence":3,' +
        '"provider":"demo_support_bot","is_demo":true,"created_at":"2026-09-01T12:00:00Z"},' +
        '"source":"demo_support_bot","is_demo":true}}';
      expect(parseSupportEvent(payload).valid).assertTrue();
      const humanPayload: string = payload.replace('"source":"demo_support_bot","is_demo":true',
        '"source":"human","is_demo":false');
      expect(parseSupportEvent(humanPayload).valid).assertTrue();
      expect(parseSupportEvent('{broken').valid).assertFalse();
      expect(shouldAcceptSupportSequence(2, 3)).assertTrue();
      expect(shouldAcceptSupportSequence(3, 3)).assertFalse();
      expect(shouldAcceptSupportSequence(3, 2)).assertFalse();
    });

    it('filtersFacilitiesByPersistedRoutePreferences', 0, () => {
      const facility: FacilityItem = new FacilityItem();
      facility.wheelchair_ok = true;
      facility.stroller_ok = false;
      expect(facilityMatchesPreference(facility, true, false)).assertTrue();
      expect(facilityMatchesPreference(facility, false, true)).assertFalse();
    });

    it('reusesCheckpointSevenIdempotencyKeysOnTransportFailure', 0, () => {
      const prefixes: string[] = ['shop-checkout', 'points-redeem', 'content-share', 'support-message'];
      for (let index: number = 0; index < prefixes.length; index++) {
        const pending: PendingIdempotentOperation = new PendingIdempotentOperation();
        const first: string = pending.getOrCreate(`operation-${index}`, prefixes[index]);
        pending.resolveFailure(503, true);
        expect(pending.getOrCreate(`operation-${index}`, prefixes[index])).assertEqual(first);
        pending.resolveSuccess();
        expect(pending.getKey()).assertEqual('');
      }
    });

    it('appliesConstrainedGlobalLargeTextScale', 0, () => {
      expect(globalContentScale(false)).assertEqual(1);
      expect(globalContentExtent(false)).assertEqual('100%');
      expect(globalContentScale(true)).assertEqual(1.04);
      expect(globalContentExtent(true)).assertEqual('96%');
      expect(classifyWindowWidth(719)).assertEqual(WindowSizeClass.COMPACT);
      expect(classifyWindowWidth(720)).assertEqual(WindowSizeClass.WIDE);
      expect(isWideWindow(1080)).assertTrue();
    });

    it('handlesConditionalManifestCacheHitsAndFallback', 0, () => {
      const notModified: NetworkResult<string> = new NetworkResult<string>(true, null, null, 304, '"pack-v1"', true);
      expect(notModified.statusCode).assertEqual(304);
      expect(notModified.notModified).assertTrue();
      expect(notModified.etag).assertEqual('"pack-v1"');
      expect(shouldUseCachedManifest(true, true)).assertTrue();
      expect(shouldUseCachedManifest(true, false)).assertFalse();
      expect(JourneyRoutePolicy.requiresAuth('/offline/packs/latest')).assertTrue();
      expect(JourneyRoutePolicy.requiresAuth('/emergency/resources')).assertTrue();
    });

    it('validatesUserSchemaAndChecksumScopedOfflineCache', 0, () => {
      const expected: OfflineAssetManifest = new OfflineAssetManifest();
      expected.id = 'asset-1';
      expected.asset_key = 'core-map';
      expected.content_hash = 'a'.repeat(64);
      expected.size_bytes = 24;
      const actual: OfflineAssetContent = new OfflineAssetContent();
      actual.id = expected.id;
      actual.asset_key = expected.asset_key;
      actual.content_hash = expected.content_hash;
      actual.size_bytes = expected.size_bytes;
      actual.encoding = 'json';
      expect(assetMatchesManifest(expected, actual)).assertTrue();
      const cache: OfflinePackCache = new OfflinePackCache();
      cache.owner_user_id = 'user-1';
      cache.pack.id = 'pack-1';
      cache.pack.version = 1;
      cache.pack.asset_count = 1;
      cache.manifest.pack_id = 'pack-1';
      cache.manifest.version = 1;
      cache.manifest.etag = '"pack-v1"';
      cache.manifest.assets = [expected];
      const cachedAsset: CachedOfflineAsset = new CachedOfflineAsset();
      cachedAsset.id = expected.id;
      cachedAsset.asset_key = expected.asset_key;
      cachedAsset.content_hash = expected.content_hash;
      cachedAsset.size_bytes = expected.size_bytes;
      cachedAsset.payload_json = '{"map":true}';
      cachedAsset.payload_fingerprint = deterministicPayloadFingerprint(cachedAsset.payload_json);
      cache.assets = [cachedAsset];
      cache.manifest_checksum = manifestFingerprint('pack-1', 1, '"pack-v1"', [expected]);
      expect(isOfflineCacheValid(cache, 'user-1')).assertTrue();
      expect(isOfflineCacheValid(cache, 'user-2')).assertFalse();
      cachedAsset.payload_json = '{"map":false}';
      expect(isOfflineCacheValid(cache, 'user-1')).assertFalse();
      cachedAsset.payload_json = '{"map":true}';
      cache.manifest_checksum = 'corrupt';
      expect(isOfflineCacheValid(cache, 'user-1')).assertFalse();
    });

    it('keepsOutboxReplayDurableAndClassifiesFailures', 0, () => {
      const outbox: OfflineOutbox = new OfflineOutbox();
      const item: OfflineOutboxItem = new OfflineOutboxItem();
      item.mutation.client_mutation_id = 'mutation-123';
      item.mutation.client_version = 1;
      item.mutation.entity_type = 'NOTE';
      item.mutation.entity_id = 'note-1';
      item.mutation.operation = 'UPSERT';
      item.mutation.payload = new JourneyJsonPayload();
      outbox.items = [item];
      expect(isSafeOfflineMutation(item.mutation)).assertTrue();
      expect(classifySyncFailure(0)).assertEqual(SyncFailureDisposition.RETRYABLE);
      expect(classifySyncFailure(503)).assertEqual(SyncFailureDisposition.RETRYABLE);
      expect(classifySyncFailure(401)).assertEqual(SyncFailureDisposition.AUTH_REQUIRED);
      expect(classifySyncFailure(409)).assertEqual(SyncFailureDisposition.TERMINAL);
      markOutboxFailure(outbox, 503, 'retry');
      expect(outbox.items[0].status).assertEqual(OfflineMutationStatus.RETRYABLE);
      const result: SyncPushResult = new SyncPushResult();
      result.client_mutation_id = 'mutation-123';
      result.status = 'REPLAYED';
      removeAppliedOutboxItems(outbox, [result]);
      expect(outbox.items.length).assertEqual(0);
      expect(offlineStateLabel(OfflineTravelState.PENDING_SYNC)).assertEqual('有待同步操作');
      const cursorError: string = '{"error":{"code":"SYNC_CURSOR_INVALID","message":"bad"}}';
      expect(extractServerErrorCode(cursorError)).assertEqual('SYNC_CURSOR_INVALID');
    });

    it('deduplicatesPulledPagesAtDurableCursorBoundary', 0, () => {
      const record: AppliedSyncRecord = new AppliedSyncRecord();
      record.client_mutation_id = 'mutation-1';
      record.server_cursor = 'opaque-cursor-1';
      const once: AppliedSyncRecord[] = mergeAppliedSyncRecords([], [record]);
      const replayed: AppliedSyncRecord[] = mergeAppliedSyncRecords(once, [record]);
      expect(once.length).assertEqual(1);
      expect(replayed.length).assertEqual(1);
    });

    it('restoresCachedEmergencyMapAndGuideDetails', 0, () => {
      const emergency: CachedOfflineAsset = new CachedOfflineAsset();
      emergency.kind = 'EMERGENCY';
      emergency.payload_json = '{"steps":["保持冷静","联系工作人员"]}';
      const guide: CachedOfflineAsset = new CachedOfflineAsset();
      guide.kind = 'GUIDE';
      guide.payload_json = '{"sections":["恢复联网后同步"]}';
      const map: CachedOfflineAsset = new CachedOfflineAsset();
      map.kind = 'MAP';
      map.payload_json = '{"version":1,"nodes":[{"code":"medical","name":"医务室"}]}';
      const narration: CachedOfflineAsset = new CachedOfflineAsset();
      narration.kind = 'NARRATION';
      narration.payload_json = '{"transcripts":["文化讲解离线文本"]}';
      const guidance: CachedGuidance = extractCachedGuidance([emergency, guide, map, narration]);
      expect(guidance.emergency_steps.length).assertEqual(2);
      expect(guidance.guide_sections[0]).assertEqual('恢复联网后同步');
      expect(guidance.map_nodes[0]).assertEqual('medical · 医务室');
      expect(guidance.narration_transcripts[0]).assertEqual('文化讲解离线文本');
    });

    it('excludesBearerSecretsAndDeliveryPiiFromTravelCache', 0, () => {
      const qr = new TicketQrResponse();
      qr.ticket_id = 'ticket-1';
      qr.ticket_code = 'T001';
      qr.qr_data = 'signed-bearer-secret';
      const ticketPayload: string = JSON.stringify(CachedTicketIdentity.fromQr(qr));
      expect(ticketPayload.includes('qr_data')).assertFalse();
      const order: ShopOrder = new ShopOrder();
      order.id = 'order-1';
      order.order_no = 'S001';
      order.delivery_phone = '13800138000';
      order.delivery_address = '敏感配送地址';
      const orderItem: ShopOrderItem = new ShopOrderItem();
      orderItem.product_name = '纪念品';
      orderItem.quantity = 1;
      order.items = [orderItem];
      const orderPayload: string = JSON.stringify(CachedShopOrder.fromOrder(order));
      expect(orderPayload.includes('delivery_phone')).assertFalse();
      expect(orderPayload.includes('delivery_address')).assertFalse();
      expect(isSafeTravelCachePayload(ticketPayload + orderPayload)).assertTrue();
      expect(isSafeTravelCachePayload('{"access_token":"secret"}')).assertFalse();
      expect(isSafeTravelCachePayload('{"password":"secret"}')).assertFalse();
      const envelope: string = createOwnedCacheEnvelope('user-1', ticketPayload + orderPayload);
      expect(readOwnedCacheEnvelope(envelope, 'user-1')).assertEqual(ticketPayload + orderPayload);
      expect(readOwnedCacheEnvelope(envelope, 'user-2')).assertEqual('');
      expect(readOwnedCacheEnvelope(envelope.substring(0, 12), 'user-1')).assertEqual('');
    });

    it('validatesSosAndGreenEvidenceWithoutClaimingDispatch', 0, () => {
      expect(validateSos('MEDICAL', '需要协助', null, null).valid).assertTrue();
      expect(validateSos('MEDICAL', '需要协助', 30.2, null).valid).assertFalse();
      expect(validateSos('UNKNOWN', '需要协助', null, null).valid).assertFalse();
      expect(validateGreenEvidence('已完成绿色出行演示').valid).assertTrue();
      expect(validateGreenEvidence('').valid).assertFalse();
    });
  });
}
