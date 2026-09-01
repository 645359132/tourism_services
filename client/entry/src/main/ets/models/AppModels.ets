export enum MainDestination {
  HOME = 0,
  GUIDE = 1,
  TRIP = 2,
  MALL = 3,
  PROFILE = 4
}

export enum ContentState {
  CONTENT = 0,
  LOADING = 1,
  EMPTY = 2,
  ERROR = 3,
  NO_PERMISSION = 4,
  WEAK_NETWORK = 5,
  OFFLINE = 6
}

export class NavigationItem {
  id: MainDestination;
  icon: string;
  label: string;

  constructor(id: MainDestination, icon: string, label: string) {
    this.id = id;
    this.icon = icon;
    this.label = label;
  }
}

export class UserSession {
  userId: string;
  displayName: string;
  accessToken: string;
  refreshToken: string;

  constructor(userId: string, displayName: string, accessToken: string, refreshToken: string = '') {
    this.userId = userId;
    this.displayName = displayName;
    this.accessToken = accessToken;
    this.refreshToken = refreshToken;
  }
}

export class AuthenticatedUser {
  id: string = '';
  username: string = '';
  display_name: string = '';
  roles: string[] = [];
}

export class AuthTokenResponse {
  access_token: string = '';
  refresh_token: string = '';
  token_type: string = 'bearer';
  expires_in: number = 0;
  user: AuthenticatedUser = new AuthenticatedUser();
}

export class ScenicSpot {
  id: string;
  name: string;
  description: string;
  distanceText: string;
  openStatus: string;

  constructor(id: string, name: string, description: string, distanceText: string, openStatus: string) {
    this.id = id;
    this.name = name;
    this.description = description;
    this.distanceText = distanceText;
    this.openStatus = openStatus;
  }
}

export class TripPlanItem {
  id: string;
  title: string;
  startAt: string;
  endAt: string;
  location: string;

  constructor(id: string, title: string, startAt: string, endAt: string, location: string) {
    this.id = id;
    this.title = title;
    this.startAt = startAt;
    this.endAt = endAt;
    this.location = location;
  }
}

export class TourismProduct {
  id: string;
  name: string;
  priceText: string;
  tag: string;

  constructor(id: string, name: string, priceText: string, tag: string) {
    this.id = id;
    this.name = name;
    this.priceText = priceText;
    this.tag = tag;
  }
}
