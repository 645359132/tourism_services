@Component
export struct AppHeader {
  @Prop title: string = '云游智景';
  @Prop subtitle: string = '智慧景区旅游服务';
  @Prop loggedIn: boolean = false;
  @Prop displayName: string = '游客';
  @Prop largeText: boolean = false;
  onLoginTap: () => void = (): void => {};

  build() {
    Row() {
      Column({ space: 2 }) {
        Text(this.title)
          .fontSize(this.largeText ? 27 : 22)
          .fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.text_primary'))
        Text(this.subtitle)
          .fontSize(this.largeText ? 15 : 12)
          .fontColor($r('app.color.text_secondary'))
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)

      Button(this.loggedIn ? this.displayName : '登录')
        .fontSize(this.largeText ? 17 : 14)
        .fontColor($r('app.color.primary'))
        .backgroundColor($r('app.color.surface_tint'))
        .height(this.largeText ? 42 : 36)
        .onClick(() => {
          this.onLoginTap();
        })
    }
    .width('100%')
    .height(this.largeText ? 76 : 64)
    .padding({ left: 20, right: 20 })
    .backgroundColor($r('app.color.surface'))
    .border({ width: { bottom: 1 }, color: $r('app.color.divider') })
  }
}
