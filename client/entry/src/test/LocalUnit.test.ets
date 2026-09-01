import { describe, expect, it } from '@ohos/hypium';
import { TripPlanItem } from '../main/ets/models/AppModels';
import { TicketOrderStatus, TicketSlot } from '../main/ets/models/TicketModels';
import { ApiErrorCode, ApiErrorInfo, mapApiError } from '../main/ets/network/ApiError';
import { ValidationResult, validateCredentials, validatePassword, validatePhone } from '../main/ets/utils/InputValidators';
import { findTripConflict, hasTripConflict } from '../main/ets/utils/TripConflict';
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
  });
}
