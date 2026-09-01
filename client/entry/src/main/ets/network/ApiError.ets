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

  constructor(code: ApiErrorCode, userMessage: string, statusCode: number, retriable: boolean) {
    this.code = code;
    this.userMessage = userMessage;
    this.statusCode = statusCode;
    this.retriable = retriable;
  }
}

export function mapApiError(statusCode: number, rawMessage: string, offline: boolean): ApiErrorInfo {
  const normalized: string = rawMessage.toLowerCase();
  if (offline) {
    return new ApiErrorInfo(ApiErrorCode.OFFLINE, '当前网络不可用，请检查网络设置', statusCode, true);
  }
  if (statusCode === 408 || normalized.includes('timeout') || normalized.includes('timed out')) {
    return new ApiErrorInfo(ApiErrorCode.TIMEOUT, '请求超时，请稍后重试', statusCode, true);
  }
  if (statusCode === 400 || statusCode === 422) {
    return new ApiErrorInfo(ApiErrorCode.VALIDATION, '提交的信息有误，请检查后重试', statusCode, false);
  }
  if (statusCode === 401) {
    return new ApiErrorInfo(ApiErrorCode.UNAUTHORIZED, '登录状态已失效，请重新登录', statusCode, false);
  }
  if (statusCode === 403) {
    return new ApiErrorInfo(ApiErrorCode.FORBIDDEN, '暂无权限访问此服务', statusCode, false);
  }
  if (statusCode === 404) {
    return new ApiErrorInfo(ApiErrorCode.NOT_FOUND, '未找到请求的内容', statusCode, false);
  }
  if (statusCode === 409) {
    return new ApiErrorInfo(ApiErrorCode.CONFLICT, '当前操作与已有数据冲突', statusCode, false);
  }
  if (statusCode === 429) {
    return new ApiErrorInfo(ApiErrorCode.RATE_LIMITED, '操作过于频繁，请稍后再试', statusCode, true);
  }
  if (statusCode >= 500 && statusCode <= 599) {
    return new ApiErrorInfo(ApiErrorCode.SERVER, '服务暂时不可用，请稍后重试', statusCode, true);
  }
  return new ApiErrorInfo(ApiErrorCode.UNKNOWN, '发生未知错误，请稍后重试', statusCode, false);
}
