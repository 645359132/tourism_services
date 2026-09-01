import { AppConfig } from '../config/AppConfig';

@Component
export struct ProfilePage {
  @Link loggedIn: boolean;
  @Link displayName: string;
  @State accessibleMode: boolean = false;
  @State offlinePackReady: boolean = false;
  @State apiUrl: string = AppConfig.getApiBaseUrl();
  @State configFeedback: string = '';
  onLoginTap: () => void = (): void => {};

  @Builder
  private serviceRow(icon: string, title: string, caption: string) {
    Row({ space: 13 }) {
      Text(icon)
        .fontSize(22)
      Column({ space: 3 }) {
        Text(title)
          .fontSize(15)
          .fontWeight(FontWeight.Medium)
          .fontColor($r('app.color.text_primary'))
        Text(caption)
          .fontSize(11)
          .fontColor($r('app.color.text_secondary'))
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)
      Text('›')
        .fontSize(22)
        .fontColor($r('app.color.text_secondary'))
    }
    .width('100%')
    .padding(16)
    .border({ width: { bottom: 1 }, color: $r('app.color.divider') })
  }

  build() {
    Scroll() {
      Column({ space: 16 }) {
        Row({ space: 15 }) {
          Text(this.loggedIn ? this.displayName.substring(0, 1) : '游')
            .width(58)
            .height(58)
            .textAlign(TextAlign.Center)
            .fontSize(24)
            .fontWeight(FontWeight.Bold)
            .fontColor(Color.White)
            .backgroundColor($r('app.color.primary'))
            .borderRadius(29)
          Column({ space: 5 }) {
            Text(this.loggedIn ? this.displayName : '游客模式')
              .fontSize(20)
              .fontWeight(FontWeight.Bold)
              .fontColor($r('app.color.text_primary'))
            Text(this.loggedIn ? '身份已验证，可继续同步业务数据' : '登录后同步多端旅行数据')
              .fontSize(12)
              .fontColor($r('app.color.text_secondary'))
          }
          .alignItems(HorizontalAlign.Start)
          .layoutWeight(1)
          if (!this.loggedIn) {
            Button('立即登录')
              .fontSize(12)
              .fontColor(Color.White)
              .backgroundColor($r('app.color.primary'))
              .onClick(() => {
                this.onLoginTap();
              })
          }
        }
        .width('100%')
        .padding(20)
        .borderRadius(22)
        .backgroundColor($r('app.color.surface'))

        Column() {
          this.serviceRow('🎫', '我的订单与电子票', '门票、预约、退款与改签')
          this.serviceRow('💬', '客服与反馈', '在线会话、投诉进度与回访')
          this.serviceRow('👥', '多人同行协作', '邀请码、共享行程与集合点')
          this.serviceRow('🏅', '文化数字护照', '到访印章、绿色任务与积分流水')
        }
        .width('100%')
        .borderRadius(20)
        .backgroundColor($r('app.color.surface'))

        Column({ space: 14 }) {
          Row() {
            Column({ space: 3 }) {
              Text('适老与无障碍模式')
                .fontSize(15)
                .fontWeight(FontWeight.Medium)
                .fontColor($r('app.color.text_primary'))
              Text('大字体、高对比度与无障碍路线入口')
                .fontSize(11)
                .fontColor($r('app.color.text_secondary'))
            }
            .alignItems(HorizontalAlign.Start)
            .layoutWeight(1)
            Toggle({ type: ToggleType.Switch, isOn: this.accessibleMode })
              .selectedColor($r('app.color.primary'))
              .onChange((value: boolean) => {
                this.accessibleMode = value;
              })
          }
          .width('100%')
          Row() {
            Column({ space: 3 }) {
              Text('弱网离线旅行包')
                .fontSize(15)
                .fontWeight(FontWeight.Medium)
                .fontColor($r('app.color.text_primary'))
              Text(this.offlinePackReady ? '电子票、地图和行程已可离线使用' : '下载核心地图、电子票、行程与讲解')
                .fontSize(11)
                .fontColor($r('app.color.text_secondary'))
            }
            .alignItems(HorizontalAlign.Start)
            .layoutWeight(1)
            Button(this.offlinePackReady ? '已下载' : '下载')
              .fontSize(12)
              .fontColor(this.offlinePackReady ? $r('app.color.success') : Color.White)
              .backgroundColor(this.offlinePackReady ? $r('app.color.surface_tint') : $r('app.color.primary'))
              .onClick(() => {
                this.offlinePackReady = true;
              })
          }
          .width('100%')
        }
        .width('100%')
        .padding(18)
        .borderRadius(20)
        .backgroundColor($r('app.color.surface'))

        Column({ space: 10 }) {
          Text('开发环境 API 地址')
            .width('100%')
            .fontSize(15)
            .fontWeight(FontWeight.Medium)
            .fontColor($r('app.color.text_primary'))
          TextInput({ text: this.apiUrl, placeholder: 'http://127.0.0.1:8000/api/v1' })
            .fontSize(12)
            .fontColor($r('app.color.text_primary'))
            .backgroundColor($r('app.color.page_background'))
            .onChange((value: string) => {
              this.apiUrl = value;
            })
          Row() {
            Text(this.configFeedback)
              .fontSize(11)
              .fontColor(this.configFeedback === '已应用' ? $r('app.color.success') : $r('app.color.error'))
              .layoutWeight(1)
            Button('应用地址')
              .fontSize(12)
              .fontColor($r('app.color.primary'))
              .backgroundColor($r('app.color.surface_tint'))
              .onClick(() => {
                this.configFeedback = AppConfig.setApiBaseUrl(this.apiUrl) ? '已应用' : '地址格式无效';
              })
          }
          .width('100%')
        }
        .width('100%')
        .padding(18)
        .borderRadius(20)
        .backgroundColor($r('app.color.surface'))
      }
      .width('100%')
      .padding({ left: 18, right: 18, top: 18, bottom: 28 })
    }
    .width('100%')
    .height('100%')
    .scrollBar(BarState.Off)
    .backgroundColor($r('app.color.page_background'))
  }
}
