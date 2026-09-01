import { UserSession } from '../models/AppModels';

export class AuthStore {
  private static instance: AuthStore = new AuthStore();
  private session: UserSession | null = null;

  static getInstance(): AuthStore {
    return AuthStore.instance;
  }

  setSession(session: UserSession): void {
    this.session = session;
  }

  clearSession(): void {
    this.session = null;
  }

  isLoggedIn(): boolean {
    return this.session !== null && this.session.accessToken.length > 0;
  }

  getDisplayName(): string {
    return this.session === null ? '游客' : this.session.displayName;
  }

  getAccessToken(): string {
    return this.session === null ? '' : this.session.accessToken;
  }
}
