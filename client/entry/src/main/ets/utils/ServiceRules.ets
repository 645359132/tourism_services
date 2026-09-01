import { FeedbackKind, FacilityItem, SupportEventEnvelope } from '../models/ServiceModels';

export class ServiceRuleResult {
  valid: boolean;
  message: string;
  constructor(valid: boolean, message: string) { this.valid = valid; this.message = message; }
}

export class SupportEventParseResult {
  valid: boolean;
  message: string;
  envelope: SupportEventEnvelope | null;
  constructor(valid: boolean, message: string, envelope: SupportEventEnvelope | null) {
    this.valid = valid; this.message = message; this.envelope = envelope;
  }
}

export function validateFeedback(kind: FeedbackKind, title: string, content: string): ServiceRuleResult {
  const knownKind: boolean = kind === FeedbackKind.FEEDBACK || kind === FeedbackKind.COMPLAINT ||
    kind === FeedbackKind.SUGGESTION;
  if (!knownKind) {
    return new ServiceRuleResult(false, '请选择反馈类型');
  }
  if (title.trim().length < 2 || title.trim().length > 160) {
    return new ServiceRuleResult(false, '标题应为 2 至 160 个字符');
  }
  if (content.trim().length < 2 || content.trim().length > 2000) {
    return new ServiceRuleResult(false, '内容应为 2 至 2000 个字符');
  }
  return new ServiceRuleResult(true, '');
}

export function validateFollowUp(rating: number, comment: string): ServiceRuleResult {
  if (!Number.isInteger(rating) || rating < 1 || rating > 5) {
    return new ServiceRuleResult(false, '回访评分应为 1 至 5 星');
  }
  if (comment.trim().length < 1 || comment.trim().length > 1000) {
    return new ServiceRuleResult(false, '回访内容应为 1 至 1000 个字符');
  }
  return new ServiceRuleResult(true, '');
}

export function validateSupportMessage(content: string): ServiceRuleResult {
  if (content.trim().length < 1 || content.trim().length > 2000) {
    return new ServiceRuleResult(false, '客服消息应为 1 至 2000 个字符');
  }
  return new ServiceRuleResult(true, '');
}

export function validateInviteCode(value: string): ServiceRuleResult {
  if (!/^[A-Za-z0-9]{6,32}$/.test(value.trim())) {
    return new ServiceRuleResult(false, '邀请码应为 6 至 32 位字母或数字');
  }
  return new ServiceRuleResult(true, '');
}

export function validateMeetingPoint(name: string, nodeId: string): ServiceRuleResult {
  if (name.trim().length < 1 || name.trim().length > 160) {
    return new ServiceRuleResult(false, '请填写 1 至 160 字的集合点名称');
  }
  return new ServiceRuleResult(true, '');
}

export function validateMemberStatus(status: string, note: string): ServiceRuleResult {
  const known: boolean = status === 'TOGETHER' || status === 'MOVING' || status === 'WAITING' || status === 'LOST';
  if (!known || note.trim().length > 500) {
    return new ServiceRuleResult(false, '请选择有效成员状态，备注最多 500 字');
  }
  return new ServiceRuleResult(true, '');
}

export function facilityMatchesPreference(item: FacilityItem, wheelchair: boolean, stroller: boolean): boolean {
  if (wheelchair && !item.wheelchair_ok) {
    return false;
  }
  if (stroller && !item.stroller_ok) {
    return false;
  }
  return true;
}

export function parseSupportEvent(payload: string): SupportEventParseResult {
  try {
    const envelope: SupportEventEnvelope = JSON.parse(payload) as SupportEventEnvelope;
    const knownType: boolean = envelope.type === 'support.message' || envelope.type === 'support.updated';
    const knownSource: boolean = envelope.data.source === 'demo_support_bot' || envelope.data.source === 'human';
    if (envelope.id.length === 0 || envelope.occurred_at.length === 0 || !knownType ||
      envelope.data.conversation.id.length === 0 || !knownSource) {
      return new SupportEventParseResult(false, '客服事件信封字段无效', null);
    }
    return new SupportEventParseResult(true, '', envelope);
  } catch (error) {
    return new SupportEventParseResult(false, '客服事件不是有效 JSON', null);
  }
}

export function shouldAcceptSupportSequence(currentSequence: number, incomingSequence: number): boolean {
  return incomingSequence > currentSequence;
}
