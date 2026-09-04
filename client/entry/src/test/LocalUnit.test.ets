import { describe, expect, it } from '@ohos/hypium';
import { TripPlanItem } from '../main/ets/models/AppModels';
import {
  ExperienceSession,
  QueueStatus,
  Reservation,
  ReservationAllocation,
  ReservationKind,
  ReservationStatus,
  SessionStatus
} from '../main/ets/models/BookingModels';
import {
  CrowdLevel,
  GuideMapNode,
  Itinerary,
  ItineraryGenerateRequest,
  ItineraryItem
} from '../main/ets/models/GuideModels';
import { TicketOrderStatus, TicketQrResponse, TicketSlot } from '../main/ets/models/TicketModels';
import { CartItem, PointsReward, ShopOrder, ShopOrderItem, ShopOrderStatus, ShopProduct } from '../main/ets/models/ShopModels';
import { FeedbackKind, FacilityItem } from '../main/ets/models/ServiceModels';
import { AppConfig } from '../main/ets/config/AppConfig';
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
import {
  ValidationResult,
  validateCredentials,
  validatePassword,
  validatePasswordConfirmation,
  validatePhone,
  validateRegistrationDisplayName,
  validateRegistrationInput,
  validateRegistrationPassword,
  validateRegistrationUsername
} from '../main/ets/utils/InputValidators';
import { findTripConflict, hasTripConflict } from '../main/ets/utils/TripConflict';
import { globalContentExtent, globalContentScale } from '../main/ets/utils/AccessibilityRules';
import { WindowSizeClass, classifyWindowWidth, isWideWindow } from '../main/ets/utils/ResponsiveRules';
import {
  detectSessionInventoryChange,
  hasActiveStayConflict,
  hasReservationConflict,
  isCurrentItinerarySuggestion,
  isTerminalQueueStatus,
  parseQueueEvent,
  reservationRenderKey,
  reservationStatusLabel,
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
  itineraryActionLabel,
  itineraryCrowdLabel,
  itineraryKindLabel,
  itinerarySeverityLabel,
  localizeItineraryText,
  localizeItineraryTexts,
  plannedRoutePathText,
  plannedRouteStepLabel,
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
      const usernameTaken: ApiErrorInfo = mapApiError(409,
        '{"error":{"code":"USERNAME_TAKEN","message":"Username is already registered"}}', false);
      const scheduleConflict: ApiErrorInfo = mapApiError(409,
        '{"error":{"code":"SCHEDULE_CONFLICT","message":"Stay overlaps an active stay booking"}}', false);
      const repeatedAction: ApiErrorInfo = mapApiError(409,
        '{"error":{"code":"IDEMPOTENCY_CONFLICT","message":"Cancellation key differs"}}', false);
      const cancelledConfirmation: ApiErrorInfo = mapApiError(409,
        '{"error":{"code":"RESERVATION_NOT_CONFIRMABLE","message":"Reservation is not confirmable"}}', false);
      const unavailableInventory: ApiErrorInfo = mapApiError(409,
        '{"error":{"code":"INVENTORY_UNAVAILABLE","message":"Stay inventory is unavailable"}}', false);

      expect(unauthorized.code).assertEqual(ApiErrorCode.UNAUTHORIZED);
      expect(unauthorized.retriable).assertFalse();
      expect(unavailable.code).assertEqual(ApiErrorCode.SERVER);
      expect(unavailable.retriable).assertTrue();
      expect(offline.code).assertEqual(ApiErrorCode.OFFLINE);
      expect(usernameTaken.code).assertEqual(ApiErrorCode.CONFLICT);
      expect(usernameTaken.statusCode).assertEqual(409);
      expect(usernameTaken.serverCode).assertEqual('USERNAME_TAKEN');
      expect(scheduleConflict.userMessage)
        .assertEqual('所选时段与已有门票或预约重叠，请更换时段或先处理已有订单');
      expect(repeatedAction.userMessage)
        .assertEqual('该操作已完成或请求内容已变化，请刷新后重试');
      expect(cancelledConfirmation.userMessage).assertEqual('预约状态已更新，当前无法确认');
      expect(unavailableInventory.userMessage).assertEqual('当前库存不足，请重新查询可用时段');
    });

    it('mapsTimeoutBeforeUnknownError', 0, () => {
      const timeout: ApiErrorInfo = mapApiError(0, 'socket timed out', false);
      expect(timeout.code).assertEqual(ApiErrorCode.TIMEOUT);
      expect(timeout.retriable).assertTrue();
    });

    it('mapsConnectionRefusalToActionableNetworkError', 0, () => {
      const refused: ApiErrorInfo = mapApiError(0, 'connect ECONNREFUSED', false);
      expect(refused.code).assertEqual(ApiErrorCode.OFFLINE);
      expect(refused.retriable).assertTrue();
      expect(refused.userMessage)
        .assertEqual('无法连接服务，请检查开发环境 API 地址和后端状态');
    });

    it('usesDevEcoEmulatorApiByDefault', 0, () => {
      expect(AppConfig.getApiBaseUrl()).assertEqual('http://10.0.2.2:8000/api/v1');
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

    it('validatesRegistrationIdentityFields', 0, () => {
      expect(validateRegistrationDisplayName(' 景区游客 ').valid).assertTrue();
      expect(validateRegistrationDisplayName('   ').valid).assertFalse();
      expect(validateRegistrationDisplayName('游'.repeat(100)).valid).assertTrue();
      expect(validateRegistrationDisplayName('游'.repeat(101)).valid).assertFalse();

      expect(validateRegistrationUsername('visitor_2026').valid).assertTrue();
      expect(validateRegistrationUsername('a'.repeat(64)).valid).assertTrue();
      expect(validateRegistrationUsername('ab').valid).assertFalse();
      expect(validateRegistrationUsername('a'.repeat(65)).valid).assertFalse();
      expect(validateRegistrationUsername('Visitor_2026').valid).assertFalse();
      expect(validateRegistrationUsername('visitor-2026').valid).assertFalse();
    });

    it('validatesRegistrationPasswordAndConfirmation', 0, () => {
      expect(validateRegistrationPassword('abcdefg1').valid).assertTrue();
      expect(validateRegistrationPassword(`${'a'.repeat(127)}1`).valid).assertTrue();
      expect(validateRegistrationPassword('abcdefg').valid).assertFalse();
      expect(validateRegistrationPassword('12345678').valid).assertFalse();
      expect(validateRegistrationPassword('abc1234').valid).assertFalse();
      expect(validateRegistrationPassword(`${'a'.repeat(128)}1`).valid).assertFalse();
      expect(validatePasswordConfirmation('Tourism123!', 'Tourism123!').valid).assertTrue();
      expect(validatePasswordConfirmation('Tourism123!', '').valid).assertFalse();
      expect(validatePasswordConfirmation('Tourism123!', 'Tourism124!').valid).assertFalse();
    });

    it('validatesCompleteRegistrationAndLongLoginPassword', 0, () => {
      const longPassword: string = `${'a'.repeat(127)}1`;
      const registration: ValidationResult = validateRegistrationInput(
        ' 景区游客 ', 'visitor_2026', 'Tourism123!', 'Tourism123!');
      expect(registration.valid).assertTrue();
      expect(validateRegistrationInput('', 'visitor_2026', 'Tourism123!', 'Tourism123!').message)
        .assertEqual('请输入显示名称');
      expect(validateRegistrationInput('景区游客', 'Visitor', 'Tourism123!', 'Tourism123!').valid).assertFalse();
      expect(validateRegistrationInput('景区游客', 'visitor', 'Tourism123!', 'mismatch').valid).assertFalse();
      expect(validateCredentials('visitor_2026', longPassword).valid).assertTrue();
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

    it('localizesPersistedItineraryPresentationText', 0, () => {
      expect(itineraryKindLabel('ATTRACTION')).assertEqual('景点');
      expect(itineraryKindLabel('COMMITMENT')).assertEqual('固定预约');
      expect(itineraryCrowdLabel('HIGH')).assertEqual('拥挤');
      expect(itinerarySeverityLabel('ERROR')).assertEqual('错误');
      expect(itineraryActionLabel('SHIFT_ITEM')).assertEqual('调整项目时间');
      expect(localizeItineraryText('Interest matches: 1 (+30)')).assertEqual('兴趣匹配 1 项（+30）');
      expect(localizeItineraryText('Simulated crowd HIGH (-40)')).assertEqual('模拟人流：拥挤（-40）');
      expect(localizeItineraryText('Schematic walk 7 min (-14)')).assertEqual('示意步行 7 分钟（-14）');
      expect(localizeItineraryText('文化博物馆: no route from previous stop'))
        .assertEqual('文化博物馆：无法从上一站到达');
      expect(localizeItineraryText('文化博物馆: missing graph or simulated crowd data'))
        .assertEqual('文化博物馆：缺少示意地图或模拟人流数据');
      expect(localizeItineraryText('文化博物馆: wheelchair accessibility unavailable'))
        .assertEqual('文化博物馆：暂不支持轮椅无障碍通行');
      expect(localizeItineraryText('文化博物馆: no accessible schematic route'))
        .assertEqual('文化博物馆：没有可用的无障碍示意路线');
      expect(localizeItineraryText('Needs 7 walking minutes plus 10 buffer minutes'))
        .assertEqual('需要 7 分钟步行时间，另加 10 分钟缓冲时间');
      expect(localizeItineraryTexts([
        'Generated by deterministic local rules; no AI provider is connected',
        'Only unlocked items were eligible for movement'
      ]).join(' · ')).assertEqual('由本地规则引擎生成，未连接外部智能模型 · 本次仅调整未锁定的行程项目');
      expect(localizeItineraryText('服务端已经返回中文')).assertEqual('服务端已经返回中文');
    });

    it('buildsVisiblePlannedRouteFeedback', 0, () => {
      const entrance: GuideMapNode = new GuideMapNode();
      entrance.id = 'entrance';
      entrance.name = '游客中心入口';
      const garden: GuideMapNode = new GuideMapNode();
      garden.id = 'garden';
      garden.name = '百草园';
      const museum: GuideMapNode = new GuideMapNode();
      museum.id = 'museum';
      museum.name = '文化博物馆';
      const routeNodeIds: string[] = ['entrance', 'garden', 'museum'];

      expect(plannedRoutePathText([entrance, garden, museum], routeNodeIds))
        .assertEqual('游客中心入口 → 百草园 → 文化博物馆');
      expect(plannedRouteStepLabel(routeNodeIds, 'entrance')).assertEqual('起');
      expect(plannedRouteStepLabel(routeNodeIds, 'garden')).assertEqual('2');
      expect(plannedRouteStepLabel(routeNodeIds, 'museum')).assertEqual('终');
      expect(plannedRouteStepLabel(routeNodeIds, 'missing')).assertEqual('');
      expect(plannedRouteStepLabel(['entrance'], 'entrance')).assertEqual('起终');
      expect(plannedRoutePathText([entrance], ['missing'])).assertEqual('未知节点');
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

    it('preventsDuplicateStayAndRefreshesReservationStateKey', 0, () => {
      const reservation: Reservation = new Reservation();
      reservation.id = 'stay-1';
      reservation.kind = ReservationKind.STAY;
      reservation.status = ReservationStatus.HELD;
      reservation.starts_at = '2026-09-05T07:00:00Z';
      reservation.ends_at = '2026-09-06T03:00:00Z';

      expect(hasActiveStayConflict([reservation], '2026-09-05', '2026-09-06')).assertTrue();
      expect(reservationStatusLabel(reservation.status)).assertEqual('待确认');
      const heldKey: string = reservationRenderKey(reservation);
      reservation.status = ReservationStatus.CONFIRMED;
      expect(hasActiveStayConflict([reservation], '2026-09-05', '2026-09-06')).assertTrue();
      expect(reservationStatusLabel(reservation.status)).assertEqual('已确认');
      expect(reservationRenderKey(reservation) === heldKey).assertFalse();
      reservation.status = ReservationStatus.CANCELLED;
      expect(hasActiveStayConflict([reservation], '2026-09-05', '2026-09-06')).assertFalse();
      expect(reservationStatusLabel(reservation.status)).assertEqual('已取消');
      expect(reservationRenderKey(reservation) === heldKey).assertFalse();
      reservation.status = ReservationStatus.EXPIRED;
      expect(hasActiveStayConflict([reservation], '2026-09-05', '2026-09-06')).assertFalse();
      reservation.status = ReservationStatus.CONFIRMED;
      expect(hasActiveStayConflict([reservation], '2026-09-06', '2026-09-07')).assertFalse();
      expect(hasActiveStayConflict([reservation], '2026-09-04', '2026-09-06')).assertTrue();
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
