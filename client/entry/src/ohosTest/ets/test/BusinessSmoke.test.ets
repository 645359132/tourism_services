import { describe, expect, it } from '@ohos/hypium';
import { TicketOrderStatus } from '../../../main/ets/models/TicketModels';
import { isSafeTravelCachePayload } from '../../../main/ets/models/PersistenceModels';
import { shanghaiDateAfterDays } from '../../../main/ets/utils/BookingRules';
import { classifySyncFailure, SyncFailureDisposition, validateSos } from '../../../main/ets/utils/JourneyRules';
import { validateRegistrationInput } from '../../../main/ets/utils/InputValidators';
import { classifyWindowWidth, WindowSizeClass } from '../../../main/ets/utils/ResponsiveRules';
import {
  canApplyTicketAction,
  TicketOrderAction,
  transitionTicketOrderStatus,
  validateTicketQuantity,
  validateVisitDate
} from '../../../main/ets/utils/TicketRules';

/**
 * Small on-device smoke suite for the business rules bundled into the HAP.
 *
 * Keep exhaustive edge cases in src/test. This suite deliberately covers one
 * critical path per cross-cutting concern so a connected phone or tablet can
 * prove that production ArkTS modules load and execute in the device runtime.
 */
export default function businessSmokeTest() {
  describe('onDeviceBusinessSmoke', () => {
    it('guardsTicketPurchaseAndPayment', 0, () => {
      expect(validateVisitDate(shanghaiDateAfterDays(1)).valid).assertTrue();
      expect(validateTicketQuantity(2, 5).valid).assertTrue();
      expect(validateTicketQuantity(6, 5).valid).assertFalse();
      expect(canApplyTicketAction(TicketOrderStatus.PENDING_PAYMENT, TicketOrderAction.PAY)).assertTrue();
      expect(transitionTicketOrderStatus(TicketOrderStatus.PENDING_PAYMENT, TicketOrderAction.PAY))
        .assertEqual(TicketOrderStatus.PAID);
    });

    it('guardsTouristRegistrationInputs', 0, () => {
      expect(validateRegistrationInput('新游客', 'new_visitor', 'Visitor123', 'Visitor123').valid)
        .assertTrue();
      expect(validateRegistrationInput('新游客', 'NewVisitor', 'Visitor123', 'Visitor123').valid)
        .assertFalse();
      expect(validateRegistrationInput('新游客', 'new_visitor', 'password', 'password').valid)
        .assertFalse();
      expect(validateRegistrationInput('新游客', 'new_visitor', 'Visitor123', 'Visitor456').valid)
        .assertFalse();
    });

    it('keepsEmergencyAndOfflineFailuresSafe', 0, () => {
      expect(validateSos('MEDICAL', '需要医务人员协助', null, null).valid).assertTrue();
      expect(validateSos('MEDICAL', '需要医务人员协助', 30.2, null).valid).assertFalse();
      expect(classifySyncFailure(503)).assertEqual(SyncFailureDisposition.RETRYABLE);
      expect(classifySyncFailure(401)).assertEqual(SyncFailureDisposition.AUTH_REQUIRED);
      expect(isSafeTravelCachePayload('{"access_token":"must-not-persist"}')).assertFalse();
    });

    it('selectsPhoneAndTabletLayoutsAtBoundary', 0, () => {
      expect(classifyWindowWidth(719)).assertEqual(WindowSizeClass.COMPACT);
      expect(classifyWindowWidth(720)).assertEqual(WindowSizeClass.WIDE);
    });
  });
}
