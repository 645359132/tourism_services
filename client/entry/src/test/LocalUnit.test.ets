import { describe, expect, it } from '@ohos/hypium';
import { TripPlanItem } from '../main/ets/models/AppModels';
import { ApiErrorCode, ApiErrorInfo, mapApiError } from '../main/ets/network/ApiError';
import { ValidationResult, validateCredentials, validatePassword, validatePhone } from '../main/ets/utils/InputValidators';
import { findTripConflict, hasTripConflict } from '../main/ets/utils/TripConflict';

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
  });
}
