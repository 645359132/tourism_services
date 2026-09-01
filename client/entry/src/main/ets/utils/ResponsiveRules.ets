export enum WindowSizeClass {
  COMPACT = 'COMPACT',
  WIDE = 'WIDE'
}

export function classifyWindowWidth(widthVp: number): WindowSizeClass {
  return widthVp >= 720 ? WindowSizeClass.WIDE : WindowSizeClass.COMPACT;
}

export function isWideWindow(widthVp: number): boolean {
  return classifyWindowWidth(widthVp) === WindowSizeClass.WIDE;
}
