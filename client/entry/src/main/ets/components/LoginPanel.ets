import { AuthTokenResponse, UserSession } from '../models/AppModels';
import { AuthService } from '../network/services/AuthService';
import { AuthStore } from '../stores/AuthStore';
import { TravelPersistenceStore } from '../stores/TravelPersistenceStore';
import {
  ValidationResult,
  validateCredentials,
  validateRegistrationInput
} from '../utils/InputValidators';

@Component
export struct LoginPanel {
  @Link visible: boolean;
  @Link loggedIn: boolean;
  @Link displayName: string;
  @State username: string = '';
  @State password: string = '';
  @State passwordConfirmation: string = '';
  @State registrationDisplayName: string = '';
  @State feedback: string = '';
  @State submitting: boolean = false;
  @State registerMode: boolean = false;
  private authService: AuthService = new AuthService();

  private clearPasswords(): void {
    this.password = '';
    this.passwordConfirmation = '';
  }

  private switchMode(registerMode: boolean): void {
    if (this.submitting || this.registerMode === registerMode) {
      return;
    }
    this.registerMode = registerMode;
    this.feedback = '';
    this.clearPasswords();
  }

  private closePanel(): void {
    if (this.submitting) {
      return;
    }
    this.feedback = '';
    this.registrationDisplayName = '';
    this.registerMode = false;
    this.clearPasswords();
    this.visible = false;
  }

  private completeAuthentication(tokenResponse: AuthTokenResponse, fallbackUsername: string): void {
    const resolvedDisplayName: string = tokenResponse.user.display_name.length > 0 ?
      tokenResponse.user.display_name : tokenResponse.user.username;
    const session: UserSession = new UserSession(tokenResponse.user.id, resolvedDisplayName,
      tokenResponse.access_token, tokenResponse.refresh_token);
    AuthStore.getInstance().setSession(session);
    TravelPersistenceStore.getInstance().saveOfflineProfile(session.userId, session.displayName);
    this.loggedIn = true;
    this.displayName = session.displayName.length > 0 ? session.displayName : fallbackUsername;
    this.closePanel();
  }

  private async submit(): Promise<void> {
    if (this.submitting) {
      return;
    }
    const registering: boolean = this.registerMode;
    const validation: ValidationResult = registering ?
      validateRegistrationInput(this.registrationDisplayName, this.username, this.password,
        this.passwordConfirmation) :
      validateCredentials(this.username, this.password);
    if (!validation.valid) {
      this.feedback = validation.message;
      return;
    }
    this.submitting = true;
    this.feedback = '';
    const result = registering ?
      await this.authService.register(this.username.trim(), this.registrationDisplayName.trim(), this.password) :
      await this.authService.login(this.username.trim(), this.password);
    this.submitting = false;
    if (!result.successful || result.data === null) {
      if (registering && result.error !== null &&
        (result.error.serverCode === 'USERNAME_TAKEN' || result.error.statusCode === 409)) {
        this.feedback = '该用户名已被使用，请更换后重试';
      } else {
        this.feedback = result.error === null ?
          (registering ? '注册失败，请稍后重试' : '登录失败，请稍后重试') : result.error.userMessage;
      }
      return;
    }
    this.completeAuthentication(result.data, this.username.trim());
  }

  build() {
    Scroll() {
      Column({ space: 16 }) {
        Row() {
          Column({ space: 4 }) {
            Text(this.registerMode ? '注册游客账号' : '游客登录')
              .fontSize(24)
              .fontWeight(FontWeight.Bold)
              .fontColor($r('app.color.text_primary'))
            Text(this.registerMode ? '创建后将自动登录并同步旅程数据' : '登录后同步订单、行程与积分')
              .fontSize(13)
              .fontColor($r('app.color.text_secondary'))
          }
          .alignItems(HorizontalAlign.Start)
          .layoutWeight(1)
          Button('关闭')
            .fontColor($r('app.color.text_secondary'))
            .backgroundColor(Color.Transparent)
            .enabled(!this.submitting)
            .onClick(() => {
              this.closePanel();
            })
        }
        .width('100%')

        Row({ space: 8 }) {
          Button('登录')
            .layoutWeight(1)
            .enabled(!this.submitting)
            .fontColor(this.registerMode ? $r('app.color.primary') : Color.White)
            .backgroundColor(this.registerMode ? $r('app.color.surface_tint') : $r('app.color.primary'))
            .onClick(() => {
              this.switchMode(false);
            })
          Button('注册')
            .layoutWeight(1)
            .enabled(!this.submitting)
            .fontColor(this.registerMode ? Color.White : $r('app.color.primary'))
            .backgroundColor(this.registerMode ? $r('app.color.primary') : $r('app.color.surface_tint'))
            .onClick(() => {
              this.switchMode(true);
            })
        }
        .width('100%')

        if (this.registerMode) {
          TextInput({ placeholder: '显示名称（1-100 个字符）', text: this.registrationDisplayName })
            .type(InputType.Normal)
            .maxLength(100)
            .height(48)
            .fontColor($r('app.color.text_primary'))
            .backgroundColor($r('app.color.page_background'))
            .enabled(!this.submitting)
            .onChange((value: string) => {
              this.registrationDisplayName = value;
            })
        }

        TextInput({
          placeholder: this.registerMode ? '用户名（小写字母、数字或下划线）' : '请输入用户名',
          text: this.username
        })
          .type(InputType.Normal)
          .maxLength(64)
          .height(48)
          .fontColor($r('app.color.text_primary'))
          .backgroundColor($r('app.color.page_background'))
          .enabled(!this.submitting)
          .onChange((value: string) => {
            this.username = value;
          })
        TextInput({
          placeholder: this.registerMode ? '密码（8-128 位，含英文字母和数字）' : '请输入密码',
          text: this.password
        })
          .type(InputType.Password)
          .maxLength(128)
          .height(48)
          .fontColor($r('app.color.text_primary'))
          .backgroundColor($r('app.color.page_background'))
          .enabled(!this.submitting)
          .onChange((value: string) => {
            this.password = value;
          })

        if (this.registerMode) {
          TextInput({ placeholder: '请再次输入密码', text: this.passwordConfirmation })
            .type(InputType.Password)
            .maxLength(128)
            .height(48)
            .fontColor($r('app.color.text_primary'))
            .backgroundColor($r('app.color.page_background'))
            .enabled(!this.submitting)
            .onChange((value: string) => {
              this.passwordConfirmation = value;
            })
        }

        if (this.feedback.length > 0) {
          Text(this.feedback)
            .width('100%')
            .fontSize(13)
            .fontColor($r('app.color.error'))
        }

        Button(this.submitting ? (this.registerMode ? '注册中…' : '登录中…') :
          (this.registerMode ? '注册并登录' : '登录'))
          .enabled(!this.submitting)
          .width('100%')
          .height(48)
          .fontColor(Color.White)
          .backgroundColor($r('app.color.primary'))
          .onClick(() => {
            this.submit();
          })
        Text(this.registerMode ? '注册将创建普通游客账号；客户端不会保存明文密码。' :
          '账号将通过配置的服务端验证；客户端不会保存明文密码。')
          .fontSize(11)
          .fontColor($r('app.color.text_secondary'))
      }
      .width('100%')
      .padding(24)
    }
    .width('90%')
    .constraintSize({ maxWidth: 440, maxHeight: '90%' })
    .scrollBar(BarState.Auto)
    .borderRadius(24)
    .backgroundColor($r('app.color.surface'))
    .clip(true)
  }
}
