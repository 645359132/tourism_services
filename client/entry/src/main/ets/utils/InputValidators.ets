export class ValidationResult {
  valid: boolean;
  message: string;

  constructor(valid: boolean, message: string) {
    this.valid = valid;
    this.message = message;
  }
}

export function validatePhone(phone: string): ValidationResult {
  const normalized: string = phone.trim();
  if (normalized.length === 0) {
    return new ValidationResult(false, '请输入手机号');
  }
  if (!/^1[3-9][0-9]{9}$/.test(normalized)) {
    return new ValidationResult(false, '请输入正确的 11 位手机号');
  }
  return new ValidationResult(true, '');
}

export function validatePassword(password: string): ValidationResult {
  if (password.length === 0) {
    return new ValidationResult(false, '请输入密码');
  }
  if (password.length < 6 || password.length > 32) {
    return new ValidationResult(false, '密码长度应为 6 至 32 位');
  }
  return new ValidationResult(true, '');
}

export function validateUsername(username: string): ValidationResult {
  const normalized: string = username.trim();
  if (normalized.length === 0) {
    return new ValidationResult(false, '请输入用户名或手机号');
  }
  if (normalized.length < 3 || normalized.length > 64) {
    return new ValidationResult(false, '用户名长度应为 3 至 64 位');
  }
  if (!/^[A-Za-z0-9_@.+-]+$/.test(normalized)) {
    return new ValidationResult(false, '用户名包含不支持的字符');
  }
  return new ValidationResult(true, '');
}

export function validateLoginInput(phone: string, password: string): ValidationResult {
  const phoneResult: ValidationResult = validatePhone(phone);
  if (!phoneResult.valid) {
    return phoneResult;
  }
  return validatePassword(password);
}

export function validateCredentials(username: string, password: string): ValidationResult {
  const usernameResult: ValidationResult = validateUsername(username);
  if (!usernameResult.valid) {
    return usernameResult;
  }
  return validatePassword(password);
}
