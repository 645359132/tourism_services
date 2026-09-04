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
  // 创新点 3：在副本上按开始时间排序，既不改变页面原顺序，又能用相邻区间一次扫描发现时间重叠。
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
