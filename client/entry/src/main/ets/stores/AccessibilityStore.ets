import { common } from '@kit.AbilityKit';
import { preferences } from '@kit.ArkData';

export class AccessibilitySettings {
  largeText: boolean = false;
  highContrast: boolean = false;
  voiceAssist: boolean = false;
  wheelchair: boolean = false;
  stroller: boolean = false;
}

export class AccessibilityStore {
  // 创新点 6：全局单例统一承载视觉与出行偏好，避免各页面各自保存而产生不一致。
  private static instance: AccessibilityStore = new AccessibilityStore();
  private preferenceStore: preferences.Preferences | null = null;
  private settings: AccessibilitySettings = new AccessibilitySettings();

  static getInstance(): AccessibilityStore {
    return AccessibilityStore.instance;
  }

  initialize(context: common.Context): void {
    try {
      const options: preferences.Options = { name: 'smart_tourism_accessibility' };
      this.preferenceStore = preferences.getPreferencesSync(context, options);
      // 启动时同步恢复偏好，使首屏即可使用上次的大字、高对比和无障碍选择。
      this.settings.largeText = this.readBoolean('large_text');
      this.settings.highContrast = this.readBoolean('high_contrast');
      this.settings.voiceAssist = this.readBoolean('voice_assist');
      this.settings.wheelchair = this.readBoolean('wheelchair');
      this.settings.stroller = this.readBoolean('stroller');
    } catch (error) {
      this.preferenceStore = null;
    }
  }

  getSettings(): AccessibilitySettings {
    // 返回快照而不是内部对象，调用方只能通过 setter 修改，从而不会绕过 Preferences 持久化。
    const copy: AccessibilitySettings = new AccessibilitySettings();
    copy.largeText = this.settings.largeText;
    copy.highContrast = this.settings.highContrast;
    copy.voiceAssist = this.settings.voiceAssist;
    copy.wheelchair = this.settings.wheelchair;
    copy.stroller = this.settings.stroller;
    return copy;
  }

  setLargeText(value: boolean): void {
    this.settings.largeText = value;
    this.persistBoolean('large_text', value);
  }

  setHighContrast(value: boolean): void {
    this.settings.highContrast = value;
    this.persistBoolean('high_contrast', value);
  }

  setVoiceAssist(value: boolean): void {
    this.settings.voiceAssist = value;
    this.persistBoolean('voice_assist', value);
  }

  setWheelchair(value: boolean): void {
    this.settings.wheelchair = value;
    this.persistBoolean('wheelchair', value);
  }

  setStroller(value: boolean): void {
    this.settings.stroller = value;
    this.persistBoolean('stroller', value);
  }

  private readBoolean(key: string): boolean {
    if (this.preferenceStore === null) {
      return false;
    }
    try {
      const value: preferences.ValueType = this.preferenceStore.getSync(key, false);
      return typeof value === 'boolean' ? value : false;
    } catch (error) {
      return false;
    }
  }

  private persistBoolean(key: string, value: boolean): void {
    if (this.preferenceStore === null) {
      return;
    }
    try {
      this.preferenceStore.putSync(key, value);
      this.preferenceStore.flushSync();
    } catch (error) {
    }
  }
}
