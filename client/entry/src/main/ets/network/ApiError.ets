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
    return new ApiErrorInfo(ApiErrorCode.CONFLICT, '当前操作与已有数据冲突', statusCode, false, serverCode);
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
