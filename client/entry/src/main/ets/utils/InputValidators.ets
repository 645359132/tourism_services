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
  if (password.length < 6 || password.length > 128) {
    return new ValidationResult(false, '密码长度应为 6 至 128 位');
  }
  return new ValidationResult(true, '');
}

export function validateRegistrationDisplayName(displayName: string): ValidationResult {
  const normalized: string = displayName.trim();
  if (normalized.length === 0) {
    return new ValidationResult(false, '请输入显示名称');
  }
  if (normalized.length > 100) {
    return new ValidationResult(false, '显示名称不能超过 100 个字符');
  }
  return new ValidationResult(true, '');
}

export function validateRegistrationUsername(username: string): ValidationResult {
  const normalized: string = username.trim();
  if (normalized.length === 0) {
    return new ValidationResult(false, '请输入用户名');
  }
  if (normalized.length < 3 || normalized.length > 64) {
    return new ValidationResult(false, '用户名长度应为 3 至 64 位');
  }
  if (!/^[a-z0-9_]+$/.test(normalized)) {
    return new ValidationResult(false, '用户名只能包含小写英文字母、数字和下划线');
  }
  return new ValidationResult(true, '');
}

export function validateRegistrationPassword(password: string): ValidationResult {
  if (password.length === 0) {
    return new ValidationResult(false, '请输入密码');
  }
  if (password.length < 8 || password.length > 128) {
    return new ValidationResult(false, '密码长度应为 8 至 128 位');
  }
  if (!/[A-Za-z]/.test(password) || !/[0-9]/.test(password)) {
    return new ValidationResult(false, '密码必须同时包含英文字母和数字');
  }
  return new ValidationResult(true, '');
}

export function validatePasswordConfirmation(password: string, confirmation: string): ValidationResult {
  if (confirmation.length === 0) {
    return new ValidationResult(false, '请再次输入密码');
  }
  if (password !== confirmation) {
    return new ValidationResult(false, '两次输入的密码不一致');
  }
  return new ValidationResult(true, '');
}

export function validateRegistrationInput(displayName: string, username: string, password: string,
  confirmation: string): ValidationResult {
  const displayNameResult: ValidationResult = validateRegistrationDisplayName(displayName);
  if (!displayNameResult.valid) {
    return displayNameResult;
  }
  const usernameResult: ValidationResult = validateRegistrationUsername(username);
  if (!usernameResult.valid) {
    return usernameResult;
  }
  const passwordResult: ValidationResult = validateRegistrationPassword(password);
  if (!passwordResult.valid) {
    return passwordResult;
  }
  return validatePasswordConfirmation(password, confirmation);
}

export function validateUsername(username: string): ValidationResult {
  const normalized: string = username.trim();
  if (normalized.length === 0) {
    return new ValidationResult(false, '请输入用户名');
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
