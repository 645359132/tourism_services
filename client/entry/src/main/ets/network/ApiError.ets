export enum ApiErrorCode {
  OFFLINE = 'OFFLINE',
  TIMEOUT = 'TIMEOUT',
  VALIDATION = 'VALIDATION',
  UNAUTHORIZED = 'UNAUTHORIZED',
  FORBIDDEN = 'FORBIDDEN',
  NOT_FOUND = 'NOT_FOUND',
  CONFLICT = 'CONFLICT',
  RATE_LIMITED = 'RATE_LIMITED',
  SERVER = 'SERVER',
  UNKNOWN = 'UNKNOWN'
}

export class ApiErrorInfo {
  code: ApiErrorCode;
  userMessage: string;
  statusCode: number;
  retriable: boolean;
  serverCode: string;

  constructor(code: ApiErrorCode, userMessage: string, statusCode: number, retriable: boolean,
    serverCode: string = '') {
    this.code = code;
    this.userMessage = userMessage;
    this.statusCode = statusCode;
    this.retriable = retriable;
    this.serverCode = serverCode;
  }
}

class ServerErrorBody {
  code: string = '';
}

class ServerErrorEnvelope {
  error: ServerErrorBody = new ServerErrorBody();
}

export function extractServerErrorCode(rawMessage: string): string {
  if (rawMessage.length === 0) { return ''; }
  try {
    const envelope: ServerErrorEnvelope = JSON.parse(rawMessage) as ServerErrorEnvelope;
    return envelope.error?.code ?? '';
  } catch (error) {
    return '';
  }
}

export function mapApiError(statusCode: number, rawMessage: string, offline: boolean): ApiErrorInfo {
  const normalized: string = rawMessage.toLowerCase();
  const serverCode: string = extractServerErrorCode(rawMessage);
  if (offline) {
    return new ApiErrorInfo(ApiErrorCode.OFFLINE, '当前网络不可用，请检查网络设置', statusCode, true, serverCode);
  }
  if (statusCode === 408 || normalized.includes('timeout') || normalized.includes('timed out')) {
    return new ApiErrorInfo(ApiErrorCode.TIMEOUT, '请求超时，请稍后重试', statusCode, true, serverCode);
  }
  if (statusCode === 400 || statusCode === 422) {
    return new ApiErrorInfo(ApiErrorCode.VALIDATION, '提交的信息有误，请检查后重试', statusCode, false, serverCode);
  }
  if (statusCode === 401) {
    return new ApiErrorInfo(ApiErrorCode.UNAUTHORIZED, '登录状态已失效，请重新登录', statusCode, false, serverCode);
  }
  if (statusCode === 403) {
    return new ApiErrorInfo(ApiErrorCode.FORBIDDEN, '暂无权限访问此服务', statusCode, false, serverCode);
  }
  if (statusCode === 404) {
    return new ApiErrorInfo(ApiErrorCode.NOT_FOUND, '未找到请求的内容', statusCode, false, serverCode);
  }
  if (statusCode === 409) {
    let conflictMessage: string = '当前操作与已有数据冲突';
    switch (serverCode) {
      case 'SCHEDULE_CONFLICT':
        conflictMessage = '所选时段与已有门票或预约重叠，请更换时段或先处理已有订单';
        break;
      case 'INSUFFICIENT_INVENTORY':
      case 'INVENTORY_UNAVAILABLE':
        conflictMessage = '当前库存不足，请重新查询可用时段';
        break;
      case 'INVENTORY_CONFLICT':
        conflictMessage = '库存状态已变化，请重新查询后再试';
        break;
      case 'RESERVATION_EXPIRED':
        conflictMessage = '预约保留已过期，请重新查询库存后预约';
        break;
      case 'RESERVATION_NOT_CONFIRMABLE':
        conflictMessage = '预约状态已更新，当前无法确认';
        break;
      case 'RESERVATION_NOT_CANCELLABLE':
        conflictMessage = '预约状态已更新，当前无法取消';
        break;
      case 'IDEMPOTENCY_CONFLICT':
        conflictMessage = '该操作已完成或请求内容已变化，请刷新后重试';
        break;
      case 'BOOKING_WINDOW_CLOSED':
        conflictMessage = '所选预约时段已经开始，请重新选择';
        break;
      case 'SESSION_CLOSED':
        conflictMessage = '所选场次已关闭，请选择其他时段';
        break;
      default:
        break;
    }
    return new ApiErrorInfo(ApiErrorCode.CONFLICT, conflictMessage, statusCode, false, serverCode);
  }
  if (statusCode === 429) {
    return new ApiErrorInfo(ApiErrorCode.RATE_LIMITED, '操作过于频繁，请稍后再试', statusCode, true, serverCode);
  }
  if (statusCode >= 500 && statusCode <= 599) {
    return new ApiErrorInfo(ApiErrorCode.SERVER, '服务暂时不可用，请稍后重试', statusCode, true, serverCode);
  }
  if (statusCode === 0) {
    return new ApiErrorInfo(ApiErrorCode.OFFLINE,
      '无法连接服务，请检查开发环境 API 地址和后端状态', statusCode, true, serverCode);
  }
  return new ApiErrorInfo(ApiErrorCode.UNKNOWN, '发生未知错误，请稍后重试', statusCode, false, serverCode);
}
