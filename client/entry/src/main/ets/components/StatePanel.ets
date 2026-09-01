import { ContentState } from '../models/AppModels';

@Component
export struct StatePanel {
  @Prop state: ContentState = ContentState.CONTENT;
  @Prop message: string = '';
  onRetry: () => void = (): void => {};

  build() {
    Column({ space: 12 }) {
      if (this.state === ContentState.LOADING) {
        LoadingProgress()
          .width(42)
          .height(42)
          .color($r('app.color.primary'))
        Text(this.message.length > 0 ? this.message : '正在加载服务数据…')
          .fontColor($r('app.color.text_secondary'))
      } else if (this.state === ContentState.EMPTY) {
        Text('◇')
          .fontSize(40)
          .fontColor($r('app.color.text_secondary'))
        Text(this.message.length > 0 ? this.message : '暂时没有可展示的内容')
          .fontColor($r('app.color.text_secondary'))
      } else if (this.state === ContentState.ERROR) {
        Text('!')
          .fontSize(30)
          .fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.error'))
        Text(this.message.length > 0 ? this.message : '加载失败，请稍后重试')
          .fontColor($r('app.color.text_primary'))
        Button('重新加载')
          .fontColor(Color.White)
          .backgroundColor($r('app.color.primary'))
          .onClick(() => {
            this.onRetry();
          })
      } else if (this.state === ContentState.NO_PERMISSION) {
        Text('🔒')
          .fontSize(30)
        Text(this.message.length > 0 ? this.message : '暂无权限，请登录或联系管理员')
          .fontColor($r('app.color.text_primary'))
      } else if (this.state === ContentState.WEAK_NETWORK) {
        Text('弱网')
          .fontSize(16)
          .fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.warning'))
        Text(this.message.length > 0 ? this.message : '网络连接较慢，已减少自动刷新')
          .fontColor($r('app.color.text_secondary'))
        Button('立即重试')
          .fontColor($r('app.color.primary'))
          .backgroundColor($r('app.color.surface_tint'))
          .onClick(() => {
            this.onRetry();
          })
      } else if (this.state === ContentState.OFFLINE) {
        Text('离线模式')
          .fontSize(16)
          .fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.warning'))
        Text(this.message.length > 0 ? this.message : '网络不可用，已切换到离线旅行包')
          .fontColor($r('app.color.text_secondary'))
        Button('恢复连接')
          .fontColor($r('app.color.primary'))
          .backgroundColor($r('app.color.surface_tint'))
          .onClick(() => {
            this.onRetry();
          })
      }
    }
    .justifyContent(FlexAlign.Center)
    .width('100%')
    .height(150)
    .padding(20)
    .borderRadius(18)
    .backgroundColor($r('app.color.surface'))
  }
}
