import { describe, expect, it } from '@ohos/hypium';
import { TripPlanItem } from '../main/ets/models/AppModels';
import {
  CrowdLevel,
  Itinerary,
  ItineraryGenerateRequest,
  ItineraryItem
} from '../main/ets/models/GuideModels';
import { TicketOrderStatus, TicketSlot } from '../main/ets/models/TicketModels';
import { ApiErrorCode, ApiErrorInfo, mapApiError } from '../main/ets/network/ApiError';
import { ValidationResult, validateCredentials, validatePassword, validatePhone } from '../main/ets/utils/InputValidators';
import { findTripConflict, hasTripConflict } from '../main/ets/utils/TripConflict';
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
  });
}
