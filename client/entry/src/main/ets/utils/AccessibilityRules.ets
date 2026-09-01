export function globalContentScale(largeText: boolean): number {
  return largeText ? 1.04 : 1;
}

export function globalContentExtent(largeText: boolean): string {
  return largeText ? '96%' : '100%';
}
