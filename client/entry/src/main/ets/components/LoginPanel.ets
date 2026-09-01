import { AuthTokenResponse, UserSession } from '../models/AppModels';
import { AuthService } from '../network/services/AuthService';
import { AuthStore } from '../stores/AuthStore';
import { ValidationResult, validateCredentials } from '../utils/InputValidators';

@Component
export struct LoginPanel {
  @Link visible: boolean;
  @Link loggedIn: boolean;
  @Link displayName: string;
  @State username: string = '';
  @State password: string = '';
  @State feedback: string = '';
  @State submitting: boolean = false;
  private authService: AuthService = new AuthService();

  private async submit(): Promise<void> {
    const validation: ValidationResult = validateCredentials(this.username, this.password);
    if (!validation.valid) {
      this.feedback = validation.message;
      return;
    }
    this.submitting = true;
    this.feedback = '';
    const result = await this.authService.login(this.username.trim(), this.password);
    this.submitting = false;
    if (!result.successful || result.data === null) {
      this.feedback = result.error === null ? '登录失败，请稍后重试' : result.error.userMessage;
      return;
    }
    const tokenResponse: AuthTokenResponse = result.data;
    const resolvedDisplayName: string = tokenResponse.user.display_name.length > 0 ?
      tokenResponse.user.display_name : tokenResponse.user.username;
    const session: UserSession = new UserSession(tokenResponse.user.id, resolvedDisplayName,
      tokenResponse.access_token, tokenResponse.refresh_token);
    AuthStore.getInstance().setSession(session);
    this.loggedIn = true;
    this.displayName = session.displayName.length > 0 ? session.displayName : this.username;
    this.password = '';
    this.visible = false;
  }

  build() {
    Column({ space: 16 }) {
      Row() {
        Column({ space: 4 }) {
          Text('游客登录')
            .fontSize(24)
            .fontWeight(FontWeight.Bold)
            .fontColor($r('app.color.text_primary'))
          Text('登录后同步订单、行程与积分')
            .fontSize(13)
            .fontColor($r('app.color.text_secondary'))
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1)
        Button('关闭')
          .fontColor($r('app.color.text_secondary'))
          .backgroundColor(Color.Transparent)
          .onClick(() => {
            this.visible = false;
          })
      }
      .width('100%')

      TextInput({ placeholder: '请输入用户名或手机号', text: this.username })
        .type(InputType.Normal)
        .height(48)
        .fontColor($r('app.color.text_primary'))
        .backgroundColor($r('app.color.page_background'))
        .onChange((value: string) => {
          this.username = value;
        })
      TextInput({ placeholder: '请输入密码', text: this.password })
        .type(InputType.Password)
        .height(48)
        .fontColor($r('app.color.text_primary'))
        .backgroundColor($r('app.color.page_background'))
        .onChange((value: string) => {
          this.password = value;
        })

      if (this.feedback.length > 0) {
        Text(this.feedback)
          .width('100%')
          .fontSize(13)
          .fontColor($r('app.color.error'))
      }

      Button(this.submitting ? '登录中…' : '登录')
        .enabled(!this.submitting)
        .width('100%')
        .height(48)
        .fontColor(Color.White)
        .backgroundColor($r('app.color.primary'))
        .onClick(() => {
          this.submit();
        })
      Text('账号将通过配置的服务端验证；客户端不会保存明文密码。')
        .fontSize(11)
        .fontColor($r('app.color.text_secondary'))
    }
    .width('90%')
    .constraintSize({ maxWidth: 440 })
    .padding(24)
    .borderRadius(24)
    .backgroundColor($r('app.color.surface'))
  }
}
