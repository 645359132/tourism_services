import { AppHeader } from '../components/AppHeader';
import { BottomNavigation, SideNavigation } from '../components/AppNavigation';
import { LoginPanel } from '../components/LoginPanel';
import { ContentState, MainDestination } from '../models/AppModels';
import { AuthStore } from '../stores/AuthStore';
import { GuidePage } from './GuidePage';
import { HomePage } from './HomePage';
import { MallPage } from './MallPage';
import { ProfilePage } from './ProfilePage';
import { TripPage } from './TripPage';
import { TicketPage } from './TicketPage';

@Entry
@Component
struct Index {
  @State selected: MainDestination = MainDestination.HOME;
  @State contentState: ContentState = ContentState.CONTENT;
  @State showLogin: boolean = false;
  @State loggedIn: boolean = false;
  @State displayName: string = '游客';
  @State isTablet: boolean = false;
  @State showTicketing: boolean = false;

  aboutToAppear(): void {
    const authStore: AuthStore = AuthStore.getInstance();
    this.loggedIn = authStore.isLoggedIn();
    this.displayName = authStore.getDisplayName();
  }

  private currentTitle(): string {
    if (this.showTicketing) {
      return '门票预约';
    }
    if (this.selected === MainDestination.GUIDE) {
      return '智慧导览';
    }
    if (this.selected === MainDestination.TRIP) {
      return '行程管家';
    }
    if (this.selected === MainDestination.MALL) {
      return '文旅商城';
    }
    if (this.selected === MainDestination.PROFILE) {
      return '个人服务';
    }
    return '云游智景';
  }

  @Builder
  private pageContent() {
    if (this.showTicketing) {
      TicketPage({
        loggedIn: this.loggedIn,
        onBack: (): void => {
          this.showTicketing = false;
        },
        onLoginTap: (): void => {
          this.showLogin = true;
        }
      })
    } else if (this.selected === MainDestination.GUIDE) {
      GuidePage()
    } else if (this.selected === MainDestination.TRIP) {
      TripPage({
        loggedIn: this.loggedIn,
        onLoginTap: (): void => {
          this.showLogin = true;
        }
      })
    } else if (this.selected === MainDestination.MALL) {
      MallPage()
    } else if (this.selected === MainDestination.PROFILE) {
      ProfilePage({
        loggedIn: $loggedIn,
        displayName: $displayName,
        onLoginTap: (): void => {
          this.showLogin = true;
        }
      })
    } else {
      HomePage({
        contentState: $contentState,
        onTicketTap: (): void => {
          this.showTicketing = true;
        }
      })
    }
  }

  build() {
    Stack({ alignContent: Alignment.Center }) {
      Row() {
        if (this.isTablet && !this.showTicketing) {
          SideNavigation({ selected: $selected })
        }
        Column() {
          AppHeader({
            title: this.currentTitle(),
            loggedIn: this.loggedIn,
            displayName: this.displayName,
            onLoginTap: (): void => {
              this.showLogin = true;
            }
          })
          Column() {
            this.pageContent()
          }
          .layoutWeight(1)
          .width('100%')
          if (!this.isTablet && !this.showTicketing) {
            BottomNavigation({ selected: $selected })
          }
        }
        .layoutWeight(1)
        .height('100%')
      }
      .width('100%')
      .height('100%')

      if (this.showLogin) {
        Column() {
          LoginPanel({
            visible: $showLogin,
            loggedIn: $loggedIn,
            displayName: $displayName
          })
        }
        .width('100%')
        .height('100%')
        .justifyContent(FlexAlign.Center)
        .backgroundColor('#66000000')
      }
    }
    .width('100%')
    .height('100%')
    .backgroundColor($r('app.color.page_background'))
    .onAreaChange((_oldArea: Area, newArea: Area) => {
      this.isTablet = Number(newArea.width) >= 720;
    })
  }
}
