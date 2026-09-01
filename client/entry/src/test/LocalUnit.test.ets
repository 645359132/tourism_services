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
import { TicketOrderStatus, TicketSlot } from '../main/ets/models/TicketModels';
import { CartItem, PointsReward, ShopOrderStatus, ShopProduct } from '../main/ets/models/ShopModels';
import { FeedbackKind, FacilityItem } from '../main/ets/models/ServiceModels';
import { ApiErrorCode, ApiErrorInfo, mapApiError } from '../main/ets/network/ApiError';
import { ValidationResult, validateCredentials, validatePassword, validatePhone } from '../main/ets/utils/InputValidators';
import { findTripConflict, hasTripConflict } from '../main/ets/utils/TripConflict';
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
  });
}
