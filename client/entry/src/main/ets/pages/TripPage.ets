import { TripPlanItem } from '../models/AppModels';
import { hasTripConflict } from '../utils/TripConflict';

const DEMO_TRIP: TripPlanItem[] = [
  new TripPlanItem('ticket', '检票入园', '2026-09-01T09:00', '2026-09-01T09:20', '东门'),
  new TripPlanItem('culture', '云山文化馆', '2026-09-01T09:40', '2026-09-01T10:30', '文化区'),
  new TripPlanItem('show', '水岸演出', '2026-09-01T11:00', '2026-09-01T11:40', '镜湖剧场')
];

@Component
export struct TripPage {
  @State optimized: boolean = false;

  @Builder
  private timelineItem(item: TripPlanItem, index: number) {
    Row({ space: 14 }) {
      Column({ space: 2 }) {
        Text(item.startAt.substring(11))
          .fontSize(14)
          .fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.primary'))
        Text(item.endAt.substring(11))
          .fontSize(11)
          .fontColor($r('app.color.text_secondary'))
      }
      .width(48)
      Column({ space: 5 }) {
        Text(item.title)
          .fontSize(16)
          .fontWeight(FontWeight.Medium)
          .fontColor($r('app.color.text_primary'))
        Text(`${item.location} · ${index === 0 ? '已预约' : '步行衔接充足'}`)
          .fontSize(12)
          .fontColor($r('app.color.text_secondary'))
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)
      Text('›')
        .fontSize(24)
        .fontColor($r('app.color.text_secondary'))
    }
    .width('100%')
    .padding(16)
    .borderRadius(18)
    .backgroundColor($r('app.color.surface'))
  }

  build() {
    Scroll() {
      Column({ space: 16 }) {
        Row() {
          Column({ space: 4 }) {
            Text('我的一日行程')
              .fontSize(22)
              .fontWeight(FontWeight.Bold)
              .fontColor($r('app.color.text_primary'))
            Text('9 月 1 日 · 3 项安排 · 预计 2 小时 40 分')
              .fontSize(12)
              .fontColor($r('app.color.text_secondary'))
          }
          .alignItems(HorizontalAlign.Start)
          .layoutWeight(1)
          Button(this.optimized ? '已优化' : '冲突检查')
            .fontSize(12)
            .fontColor(this.optimized ? $r('app.color.success') : $r('app.color.primary'))
            .backgroundColor($r('app.color.surface_tint'))
            .onClick(() => {
              this.optimized = !hasTripConflict(DEMO_TRIP);
            })
        }
        .width('100%')

        if (this.optimized) {
          Text('✓ 未发现时间冲突，已预留步行缓冲')
            .width('100%')
            .padding(12)
            .borderRadius(12)
            .fontSize(12)
            .fontColor($r('app.color.success'))
            .backgroundColor($r('app.color.surface_tint'))
        }

        ForEach(DEMO_TRIP, (item: TripPlanItem, index: number) => {
          this.timelineItem(item, index)
        }, (item: TripPlanItem) => item.id)

        Row({ space: 12 }) {
          Column({ space: 5 }) {
            Text('规则行程管家')
              .fontSize(16)
              .fontWeight(FontWeight.Bold)
              .fontColor($r('app.color.text_primary'))
            Text('按兴趣、体力、人流和预约自动评分重排')
              .fontSize(12)
              .fontColor($r('app.color.text_secondary'))
          }
          .alignItems(HorizontalAlign.Start)
          .layoutWeight(1)
          Button('重新规划')
            .fontColor(Color.White)
            .backgroundColor($r('app.color.primary'))
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
