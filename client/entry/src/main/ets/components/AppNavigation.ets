import { MainDestination, NavigationItem } from '../models/AppModels';

const MAIN_NAV_ITEMS: NavigationItem[] = [
  new NavigationItem(MainDestination.HOME, '⌂', '首页'),
  new NavigationItem(MainDestination.GUIDE, '⌖', '导览'),
  new NavigationItem(MainDestination.TRIP, '◇', '行程'),
  new NavigationItem(MainDestination.MALL, '▣', '商城'),
  new NavigationItem(MainDestination.PROFILE, '○', '我的')
];

@Component
export struct BottomNavigation {
  @Link selected: MainDestination;

  build() {
    Row() {
      ForEach(MAIN_NAV_ITEMS, (item: NavigationItem) => {
        Column({ space: 3 }) {
          Text(item.icon)
            .fontSize(19)
            .fontColor(this.selected === item.id ? $r('app.color.primary') : $r('app.color.text_secondary'))
          Text(item.label)
            .fontSize(11)
            .fontWeight(this.selected === item.id ? FontWeight.Medium : FontWeight.Regular)
            .fontColor(this.selected === item.id ? $r('app.color.primary') : $r('app.color.text_secondary'))
        }
        .justifyContent(FlexAlign.Center)
        .layoutWeight(1)
        .height(60)
        .onClick(() => {
          this.selected = item.id;
        })
      }, (item: NavigationItem) => item.id.toString())
    }
    .width('100%')
    .height(60)
    .backgroundColor($r('app.color.surface'))
    .border({ width: { top: 1 }, color: $r('app.color.divider') })
  }
}

@Component
export struct SideNavigation {
  @Link selected: MainDestination;

  build() {
    Column({ space: 8 }) {
      Text('云游')
        .fontSize(20)
        .fontWeight(FontWeight.Bold)
        .fontColor($r('app.color.primary'))
        .margin({ top: 22, bottom: 18 })
      ForEach(MAIN_NAV_ITEMS, (item: NavigationItem) => {
        Row({ space: 12 }) {
          Text(item.icon)
            .fontSize(20)
            .fontColor(this.selected === item.id ? $r('app.color.primary') : $r('app.color.text_secondary'))
          Text(item.label)
            .fontSize(15)
            .fontWeight(this.selected === item.id ? FontWeight.Bold : FontWeight.Regular)
            .fontColor(this.selected === item.id ? $r('app.color.primary') : $r('app.color.text_secondary'))
        }
        .width(116)
        .height(48)
        .padding({ left: 16 })
        .borderRadius(14)
        .backgroundColor(this.selected === item.id ? $r('app.color.surface_tint') : Color.Transparent)
        .onClick(() => {
          this.selected = item.id;
        })
      }, (item: NavigationItem) => item.id.toString())
    }
    .height('100%')
    .width(144)
    .alignItems(HorizontalAlign.Center)
    .backgroundColor($r('app.color.surface'))
    .border({ width: { right: 1 }, color: $r('app.color.divider') })
  }
}
