import { StatePanel } from '../components/StatePanel';
import { ContentState } from '../models/AppModels';

@Component
export struct HomePage {
  @Link contentState: ContentState;
  onTicketTap: () => void = (): void => {};

  @Builder
  private quickService(icon: string, title: string, caption: string) {
    Column({ space: 7 }) {
      Text(icon)
        .fontSize(26)
      Text(title)
        .fontSize(15)
        .fontWeight(FontWeight.Medium)
        .fontColor($r('app.color.text_primary'))
      Text(caption)
        .fontSize(11)
        .fontColor($r('app.color.text_secondary'))
        .maxLines(1)
    }
    .width('48%')
    .height(112)
    .justifyContent(FlexAlign.Center)
    .borderRadius(18)
    .backgroundColor($r('app.color.surface'))
    .onClick(() => {
      if (title === '门票预约') {
        this.onTicketTap();
      }
    })
  }

  @Builder
  private stateButton(label: string, state: ContentState) {
    Button(label)
      .height(34)
      .fontSize(12)
      .fontColor(this.contentState === state ? Color.White : $r('app.color.primary'))
      .backgroundColor(this.contentState === state ? $r('app.color.primary') : $r('app.color.surface_tint'))
      .onClick(() => {
        this.contentState = state;
      })
  }

  build() {
    Scroll() {
      Column({ space: 18 }) {
        Column({ space: 8 }) {
          Row() {
            Text('今日畅游推荐')
              .fontSize(25)
              .fontWeight(FontWeight.Bold)
              .fontColor(Color.White)
              .layoutWeight(1)
            Text('舒适')
              .fontSize(12)
              .fontColor(Color.White)
              .padding({ left: 10, right: 10, top: 5, bottom: 5 })
              .borderRadius(12)
              .backgroundColor('#33FFFFFF')
          }
          .width('100%')
          Text('09:30 入园 · 东线文化主题路线 · 预计 4 小时')
            .fontSize(13)
            .fontColor('#E8F2FF')
          Row({ space: 10 }) {
            Button('生成个性行程')
              .fontSize(13)
              .fontColor($r('app.color.primary'))
              .backgroundColor(Color.White)
            Button('查看实时人流')
              .fontSize(13)
              .fontColor(Color.White)
              .backgroundColor('#22FFFFFF')
          }
          .width('100%')
          .margin({ top: 8 })
        }
        .width('100%')
        .padding(20)
        .borderRadius(24)
        .linearGradient({ angle: 135, colors: [['#1677FF', 0.0], ['#36A9E1', 1.0]] })

        Row() {
          Text('快捷服务')
            .fontSize(18)
            .fontWeight(FontWeight.Bold)
            .fontColor($r('app.color.text_primary'))
            .layoutWeight(1)
          Text('全部服务  ›')
            .fontSize(13)
            .fontColor($r('app.color.primary'))
        }
        .width('100%')

        Flex({ wrap: FlexWrap.Wrap, justifyContent: FlexAlign.SpaceBetween, alignContent: FlexAlign.SpaceBetween }) {
          this.quickService('🎫', '门票预约', '分时库存与动态价格')
          this.quickService('⏱', '智慧排队', '等待变化联动行程')
          this.quickService('🏨', '餐住预订', '住玩与餐玩组合')
          this.quickService('🆘', '应急助手', '离线指引与 SOS')
        }
        .width('100%')
        .height(236)

        Column({ space: 10 }) {
          Row() {
            Text('状态与异常演示')
              .fontSize(18)
              .fontWeight(FontWeight.Bold)
              .fontColor($r('app.color.text_primary'))
              .layoutWeight(1)
            Text('用于验收')
              .fontSize(11)
              .fontColor($r('app.color.text_secondary'))
          }
          .width('100%')
          Scroll() {
            Row({ space: 8 }) {
              this.stateButton('正常', ContentState.CONTENT)
              this.stateButton('加载', ContentState.LOADING)
              this.stateButton('空数据', ContentState.EMPTY)
              this.stateButton('失败/重试', ContentState.ERROR)
              this.stateButton('无权限', ContentState.NO_PERMISSION)
              this.stateButton('弱网', ContentState.WEAK_NETWORK)
              this.stateButton('离线', ContentState.OFFLINE)
            }
          }
          .scrollable(ScrollDirection.Horizontal)
          .scrollBar(BarState.Off)
          .width('100%')

          if (this.contentState !== ContentState.CONTENT) {
            StatePanel({
              state: this.contentState,
              onRetry: (): void => {
                this.contentState = ContentState.LOADING;
                setTimeout(() => {
                  this.contentState = ContentState.CONTENT;
                }, 500);
              }
            })
          } else {
            Row({ space: 12 }) {
              Text('✓')
                .fontSize(22)
                .fontColor($r('app.color.success'))
              Column({ space: 3 }) {
                Text('客户端应用壳已就绪')
                  .fontSize(15)
                  .fontWeight(FontWeight.Medium)
                  .fontColor($r('app.color.text_primary'))
                Text('登录可连接服务端；库存、人流和行程将在后续检查点接入')
                  .fontSize(12)
                  .fontColor($r('app.color.text_secondary'))
              }
              .alignItems(HorizontalAlign.Start)
            }
            .width('100%')
            .padding(18)
            .borderRadius(18)
            .backgroundColor($r('app.color.surface'))
          }
        }
        .width('100%')
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
