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
    if (serverCode === 'INVALID_QUOTE') {
      return new ApiErrorInfo(
        ApiErrorCode.VALIDATION, '门票报价凭证无效，请重新获取价格', statusCode, false, serverCode);
    }
    return new ApiErrorInfo(ApiErrorCode.VALIDATION, '提交的信息有误，请检查后重试', statusCode, false, serverCode);
  }
  if (statusCode === 401) {
    return new ApiErrorInfo(ApiErrorCode.UNAUTHORIZED, '登录状态已失效，请重新登录', statusCode, false, serverCode);
  }
  if (statusCode === 403) {
    return new ApiErrorInfo(ApiErrorCode.FORBIDDEN, '暂无权限访问此服务', statusCode, false, serverCode);
  }
  if (statusCode === 404) {
    if (serverCode === 'PRODUCT_NOT_FOUND') {
      return new ApiErrorInfo(ApiErrorCode.NOT_FOUND, '商品已下架，已为你刷新目录', statusCode, false, serverCode);
    }
    if (serverCode === 'CART_ITEM_NOT_FOUND') {
      return new ApiErrorInfo(
        ApiErrorCode.NOT_FOUND, '购物车商品已变化，已为你刷新购物车', statusCode, false, serverCode);
    }
    return new ApiErrorInfo(ApiErrorCode.NOT_FOUND, '未找到请求的内容', statusCode, false, serverCode);
  }
  if (statusCode === 409) {
    let conflictMessage: string = '当前操作与已有数据冲突';
    switch (serverCode) {
      case 'SCHEDULE_CONFLICT':
        conflictMessage = '所选时段与已有有效预约重叠，请更换时段或先处理已有预约';
        break;
      case 'INSUFFICIENT_INVENTORY':
      case 'INVENTORY_UNAVAILABLE':
        conflictMessage = '当前库存不足，请重新查询可用时段';
        break;
      case 'INVENTORY_CONFLICT':
        conflictMessage = '库存状态已变化，请重新查询后再试';
        break;
      case 'INSUFFICIENT_STOCK':
        conflictMessage = '商品余量不足，已为你刷新商品与购物车';
        break;
      case 'PRODUCT_UNAVAILABLE':
        conflictMessage = '商品已下架或暂不可售，已为你刷新目录';
        break;
      case 'CART_CONFLICT':
        conflictMessage = '购物车内容已变化，已为你刷新后请重新结算';
        break;
      case 'CART_EMPTY':
        conflictMessage = '购物车已为空，请返回商品页重新选择';
        break;
      case 'SHOP_ORDER_EXPIRED':
        conflictMessage = '待支付订单已过期，预占库存已经释放';
        break;
      case 'SHOP_ORDER_NOT_PAYABLE':
        conflictMessage = '商城订单已过期或状态已变化，当前无法支付';
        break;
      case 'CHECKOUT_CONFLICT':
        conflictMessage = '结算期间购物车或库存已变化，已刷新后请重试';
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
      case 'SLOT_CLOSED':
        conflictMessage = '所选门票时段已关闭，请重新选择';
        break;
      case 'ORDER_NOT_PAYABLE':
        conflictMessage = '订单已过期或状态已变化，当前无法支付';
        break;
      case 'QUOTE_EXPIRED':
        conflictMessage = '门票报价已过期，请重新获取价格';
        break;
      case 'QUOTE_MISMATCH':
        conflictMessage = '门票日期、场次、数量或报价不匹配，请重新选择';
        break;
      case 'REFUND_WINDOW_CLOSED':
        conflictMessage = '已超过服务端返回的退票截止时间，当前无法退款';
        break;
      case 'ORDER_NOT_REFUNDABLE':
        conflictMessage = '仅已支付的有效订单可以申请退款';
        break;
      case 'TICKET_ALREADY_USED':
        conflictMessage = '电子票已核验或失效，无法办理退票或改签';
        break;
      case 'REFUND_CONFLICT':
        conflictMessage = '订单或库存状态已变化，请刷新订单后重试';
        break;
      case 'ORDER_NOT_CANCELLABLE':
        conflictMessage = '仅待支付订单可以取消，请刷新订单状态';
        break;
      case 'ORDER_NOT_RESCHEDULABLE':
        conflictMessage = '仅持有未核验电子票的已支付订单可以改签';
        break;
      case 'SAME_SLOT':
        conflictMessage = '目标时段与当前时段相同，请选择其他时段';
        break;
      case 'TICKET_TYPE_MISMATCH':
        conflictMessage = '目标时段的票种不同，请选择同一票种';
        break;
      case 'RESCHEDULE_PRICE_DELTA_UNSUPPORTED':
        conflictMessage = '目标时段价格不同，演示系统暂不支持补差价改签';
        break;
      case 'RESCHEDULE_CONFLICT':
        conflictMessage = '改签期间订单或库存已变化，请刷新后重试';
        break;
      case 'TICKET_NOT_VALID':
        conflictMessage = '电子票已核验、失效或状态已变化';
        break;
      case 'TICKET_OUTSIDE_VALIDATION_WINDOW':
        conflictMessage = '当前不在该电子票的可核验时段内';
        break;
      case 'FACE_DEMO_TICKET_NOT_ELIGIBLE':
        conflictMessage = '电子票状态已变化，当前无法进行人脸核验演示';
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
