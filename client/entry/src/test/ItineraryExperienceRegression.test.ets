import { describe, expect, it } from '@ohos/hypium';
import {
  Reservation,
  ReservationAllocation,
  ReservationKind,
  ReservationStatus
} from '../main/ets/models/BookingModels';
import { hasReservationConflict } from '../main/ets/utils/BookingRules';

function confirmedStay(): Reservation {
  const allocation: ReservationAllocation = new ReservationAllocation();
  allocation.starts_at = '2026-09-05T07:00:00Z';
  allocation.ends_at = '2026-09-06T03:00:00Z';
  const reservation: Reservation = new Reservation();
  reservation.kind = ReservationKind.STAY;
  reservation.status = ReservationStatus.CONFIRMED;
  reservation.starts_at = allocation.starts_at;
  reservation.ends_at = allocation.ends_at;
  reservation.allocations = [allocation];
  return reservation;
}

export default function itineraryExperienceRegressionTest() {
  describe('itineraryExperienceRegressions', () => {
    it('lodgingDoesNotOccupyEveryMinuteBetweenCheckInAndCheckOut', 0, () => {
      const stay: Reservation = confirmedStay();
      expect(hasReservationConflict(
        [stay], '2026-09-05T12:00:00Z', '2026-09-05T12:45:00Z')).assertFalse();
      expect(hasReservationConflict(
        [stay], '2026-09-05T07:10:00Z', '2026-09-05T07:20:00Z')).assertTrue();
      expect(hasReservationConflict(
        [stay], '2026-09-06T02:40:00Z', '2026-09-06T02:50:00Z')).assertTrue();
    });

    it('experienceConflictsUseHalfOpenIntervals', 0, () => {
      const allocation: ReservationAllocation = new ReservationAllocation();
      allocation.starts_at = '2026-09-05T02:00:00Z';
      allocation.ends_at = '2026-09-05T02:45:00Z';
      const reservation: Reservation = new Reservation();
      reservation.kind = ReservationKind.EXPERIENCE;
      reservation.status = ReservationStatus.HELD;
      reservation.allocations = [allocation];
      expect(hasReservationConflict(
        [reservation], '2026-09-05T02:30:00Z', '2026-09-05T03:00:00Z')).assertTrue();
      expect(hasReservationConflict(
        [reservation], '2026-09-05T02:45:00Z', '2026-09-05T03:10:00Z')).assertFalse();
    });
  });
}
