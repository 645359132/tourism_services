import {
  Attraction,
  CrowdEnvelope,
  CrowdItem,
  CrowdLevel,
  Itinerary,
  ItineraryGenerateRequest,
  ItineraryItem
} from '../models/GuideModels';

export class GuideRuleResult {
  valid: boolean;
  message: string;

  constructor(valid: boolean, message: string) {
    this.valid = valid;
    this.message = message;
  }
}

export class CrowdEnvelopeParseResult {
  valid: boolean;
  message: string;
  envelope: CrowdEnvelope | null;

  constructor(valid: boolean, message: string, envelope: CrowdEnvelope | null) {
    this.valid = valid;
    this.message = message;
    this.envelope = envelope;
  }
}

export class TimelineConflictDisplay {
  conflicted: boolean;
  firstItemId: string;
  secondItemId: string;
  message: string;

  constructor(conflicted: boolean, firstItemId: string, secondItemId: string, message: string) {
    this.conflicted = conflicted;
    this.firstItemId = firstItemId;
    this.secondItemId = secondItemId;
    this.message = message;
  }
}

export class ReplanAssessment {
  accepted: boolean;
  message: string;

  constructor(accepted: boolean, message: string) {
    this.accepted = accepted;
    this.message = message;
  }
}

export function classifyCrowdLevel(occupancyBps: number, waitMinutes: number): CrowdLevel {
  if (occupancyBps >= 7500 || waitMinutes >= 40) {
    return CrowdLevel.HIGH;
  }
  if (occupancyBps >= 4500 || waitMinutes >= 20) {
    return CrowdLevel.MEDIUM;
  }
  return CrowdLevel.LOW;
}

export function shouldAcceptCrowdSequence(currentSequence: number, incomingSequence: number): boolean {
  return incomingSequence > currentSequence;
}

export function parseCrowdEnvelope(payload: string): CrowdEnvelopeParseResult {
  if (payload.trim().length === 0) {
    return new CrowdEnvelopeParseResult(false, '人流消息为空', null);
  }
  try {
    const envelope: CrowdEnvelope = JSON.parse(payload) as CrowdEnvelope;
    if (envelope.id.length === 0 || envelope.type !== 'crowd.snapshot' || envelope.occurred_at.length === 0) {
      return new CrowdEnvelopeParseResult(false, '人流消息信封字段无效', null);
    }
    if (envelope.data.sequence < 0 || envelope.data.source !== 'simulated' || !envelope.data.is_demo ||
      envelope.data.items === undefined) {
      return new CrowdEnvelopeParseResult(false, '人流快照边界字段无效', null);
    }
    return new CrowdEnvelopeParseResult(true, '', envelope);
  } catch (error) {
    return new CrowdEnvelopeParseResult(false, '人流消息不是有效 JSON', null);
  }
}

export function validateItineraryGenerateInput(input: ItineraryGenerateRequest): GuideRuleResult {
  if (!/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(input.visit_date)) {
    return new GuideRuleResult(false, '游玩日期格式应为 YYYY-MM-DD');
  }
  if (!/^([01][0-9]|2[0-3]):[0-5][0-9]$/.test(input.start_time)) {
    return new GuideRuleResult(false, '开始时间格式应为 HH:mm');
  }
  if (!Number.isInteger(input.duration_minutes) || input.duration_minutes < 60 || input.duration_minutes > 720) {
    return new GuideRuleResult(false, '游玩时长应为 60 至 720 分钟');
  }
  if (input.interests.length === 0) {
    return new GuideRuleResult(false, '请至少选择一个兴趣');
  }
  const validCompanion: boolean = input.companion_type === 'solo' || input.companion_type === 'family' ||
    input.companion_type === 'friends' || input.companion_type === 'senior';
  if (!validCompanion) {
    return new GuideRuleResult(false, '同行类型无效');
  }
  const validFitness: boolean = input.fitness_level === 'low' || input.fitness_level === 'medium' ||
    input.fitness_level === 'high';
  if (!validFitness) {
    return new GuideRuleResult(false, '体力等级无效');
  }
  return new GuideRuleResult(true, '');
}

export function findTimelineConflict(items: ItineraryItem[]): TimelineConflictDisplay {
  const ordered: ItineraryItem[] = items.slice();
  ordered.sort((left: ItineraryItem, right: ItineraryItem): number => left.start_at.localeCompare(right.start_at));
  for (let index: number = 0; index < ordered.length - 1; index++) {
    const current: ItineraryItem = ordered[index];
    const next: ItineraryItem = ordered[index + 1];
    if (current.start_at < current.end_at && next.start_at < next.end_at && next.start_at < current.end_at) {
      return new TimelineConflictDisplay(true, current.id, next.id,
        `${current.title} 与 ${next.title} 的时间发生重叠`);
    }
  }
  return new TimelineConflictDisplay(false, '', '', '时间轴未发现直接重叠');
}

function findItineraryItem(items: ItineraryItem[], itemId: string, refId: string): ItineraryItem | null {
  for (let index: number = 0; index < items.length; index++) {
    if (items[index].id === itemId || (refId.length > 0 && items[index].ref_id === refId)) {
      return items[index];
    }
  }
  return null;
}

export function assessReplan(previous: Itinerary, updated: Itinerary): ReplanAssessment {
  if (updated.id !== previous.id || updated.revision <= previous.revision) {
    return new ReplanAssessment(false, '重排版本无效，已保留当前行程');
  }
  for (let index: number = 0; index < previous.items.length; index++) {
    const lockedItem: ItineraryItem = previous.items[index];
    if (!lockedItem.locked) {
      continue;
    }
    const updatedItem: ItineraryItem | null = findItineraryItem(updated.items, lockedItem.id, lockedItem.ref_id);
    if (updatedItem === null || updatedItem.start_at !== lockedItem.start_at || updatedItem.end_at !== lockedItem.end_at) {
      return new ReplanAssessment(false, `锁定预约“${lockedItem.title}”被移动，已拒绝本次重排`);
    }
  }
  return new ReplanAssessment(true, '已按最新模拟人流重排，锁定预约保持不变');
}

function crowdRank(level: CrowdLevel): number {
  if (level === CrowdLevel.HIGH) {
    return 3;
  }
  if (level === CrowdLevel.MEDIUM) {
    return 2;
  }
  return 1;
}

function attractionName(attractions: Attraction[], attractionId: string): string {
  for (let index: number = 0; index < attractions.length; index++) {
    if (attractions[index].id === attractionId) {
      return attractions[index].name;
    }
  }
  return '当前景点';
}

export function buildCrowdAlternative(attractions: Attraction[], crowdItems: CrowdItem[]): string {
  if (crowdItems.length < 2) {
    return '等待更多模拟人流数据后生成替代路线';
  }
  let busiest: CrowdItem = crowdItems[0];
  let quietest: CrowdItem = crowdItems[0];
  for (let index: number = 1; index < crowdItems.length; index++) {
    if (crowdRank(crowdItems[index].level) > crowdRank(busiest.level)) {
      busiest = crowdItems[index];
    }
    if (crowdRank(crowdItems[index].level) < crowdRank(quietest.level)) {
      quietest = crowdItems[index];
    }
  }
  if (busiest.attraction_id === quietest.attraction_id || busiest.level !== CrowdLevel.HIGH) {
    return '当前模拟人流较均衡，可按原路线游览';
  }
  return `${attractionName(attractions, busiest.attraction_id)}较拥挤，建议先游览` +
    `${attractionName(attractions, quietest.attraction_id)}（预计等待 ${quietest.wait_minutes} 分钟）`;
}
