import { TripPlanItem } from '../models/AppModels';

export class TripConflictResult {
  conflicted: boolean;
  firstItemId: string;
  secondItemId: string;

  constructor(conflicted: boolean, firstItemId: string, secondItemId: string) {
    this.conflicted = conflicted;
    this.firstItemId = firstItemId;
    this.secondItemId = secondItemId;
  }
}

export function isValidTripRange(item: TripPlanItem): boolean {
  return item.startAt.length > 0 && item.endAt.length > 0 && item.startAt < item.endAt;
}

export function findTripConflict(items: TripPlanItem[]): TripConflictResult {
  const ordered: TripPlanItem[] = items.slice();
  ordered.sort((left: TripPlanItem, right: TripPlanItem): number => left.startAt.localeCompare(right.startAt));
  for (let index: number = 0; index < ordered.length - 1; index++) {
    const current: TripPlanItem = ordered[index];
    const next: TripPlanItem = ordered[index + 1];
    if (isValidTripRange(current) && isValidTripRange(next) && next.startAt < current.endAt) {
      return new TripConflictResult(true, current.id, next.id);
    }
  }
  return new TripConflictResult(false, '', '');
}

export function hasTripConflict(items: TripPlanItem[]): boolean {
  return findTripConflict(items).conflicted;
}
