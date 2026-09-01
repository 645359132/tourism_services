import { ScenicSpot } from '../models/AppModels';

const GUIDE_SPOTS: ScenicSpot[] = [
  new ScenicSpot('gate', '游客中心', '票务、咨询、寄存与无障碍服务', '距您 120m', '开放中'),
  new ScenicSpot('museum', '云山文化馆', '地方历史与非遗数字讲解', '步行 6 分钟', '舒适'),
  new ScenicSpot('lake', '镜湖观景台', '亲水栈道与日落最佳机位', '步行 12 分钟', '较拥挤')
];

@Component
export struct GuidePage {
  @Builder
  private spotCard(spot: ScenicSpot) {
    Row({ space: 14 }) {
      Column() {
        Text(spot.id === 'museum' ? '文' : spot.id === 'lake' ? '景' : '服')
          .fontSize(20)
          .fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.primary'))
      }
      .width(52)
      .height(52)
      .justifyContent(FlexAlign.Center)
      .borderRadius(16)
      .backgroundColor($r('app.color.surface_tint'))

      Column({ space: 4 }) {
        Row() {
          Text(spot.name)
            .fontSize(16)
            .fontWeight(FontWeight.Medium)
            .fontColor($r('app.color.text_primary'))
            .layoutWeight(1)
          Text(spot.openStatus)
            .fontSize(11)
            .fontColor(spot.openStatus === '较拥挤' ? $r('app.color.warning') : $r('app.color.success'))
        }
        .width('100%')
        Text(spot.description)
          .fontSize(12)
          .fontColor($r('app.color.text_secondary'))
          .maxLines(1)
        Text(spot.distanceText)
          .fontSize(11)
          .fontColor($r('app.color.primary'))
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)
    }
    .width('100%')
    .padding(15)
    .borderRadius(18)
    .backgroundColor($r('app.color.surface'))
  }

  build() {
    Scroll() {
      Column({ space: 16 }) {
        Column({ space: 12 }) {
          Row() {
            Text('景区示意导览')
              .fontSize(20)
              .fontWeight(FontWeight.Bold)
              .fontColor($r('app.color.text_primary'))
              .layoutWeight(1)
            Text('地图适配器 · 演示')
              .fontSize(11)
              .fontColor($r('app.color.text_secondary'))
          }
          .width('100%')
          Stack({ alignContent: Alignment.Center }) {
            Column({ space: 16 }) {
              Row({ space: 55 }) {
                Text('● 文化馆').fontColor($r('app.color.primary'))
                Text('● 观景台').fontColor($r('app.color.warning'))
              }
              Text('······  推荐低拥堵路线  ······')
                .fontSize(12)
                .fontColor($r('app.color.success'))
              Row({ space: 58 }) {
                Text('◎ 我的位置').fontColor($r('app.color.primary'))
                Text('● 游客中心').fontColor($r('app.color.text_secondary'))
              }
            }
          }
          .width('100%')
          .height(190)
          .borderRadius(20)
          .backgroundColor($r('app.color.surface_tint'))
          Row({ space: 8 }) {
            Button('定位演示')
              .fontColor(Color.White)
              .backgroundColor($r('app.color.primary'))
            Button('人流热力')
              .fontColor($r('app.color.warning'))
              .backgroundColor($r('app.color.surface'))
            Button('语音讲解')
              .fontColor($r('app.color.primary'))
              .backgroundColor($r('app.color.surface'))
          }
          .width('100%')
        }
        .padding(18)
        .borderRadius(24)
        .backgroundColor($r('app.color.surface'))

        Text('附近景点')
          .width('100%')
          .fontSize(18)
          .fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.text_primary'))
        ForEach(GUIDE_SPOTS, (spot: ScenicSpot) => {
          this.spotCard(spot)
        }, (spot: ScenicSpot) => spot.id)
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
