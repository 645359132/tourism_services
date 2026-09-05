import { describe, expect, it } from '@ohos/hypium';
import {
  formatScenicClock,
  formatShanghaiDateTime,
  formatShanghaiRange,
  formatShanghaiTime
} from '../main/ets/utils/DateTimeRules';

export default function dateTimeRulesTest() {
  describe('dateTimeRules', () => {
    it('normalizesApiTimesToAsiaShanghai', 0, () => {
      expect(formatShanghaiDateTime('2026-09-05T07:00:00Z')).assertEqual('2026-09-05 15:00');
      expect(formatShanghaiDateTime('2026-09-05T07:00:00+00:00')).assertEqual('2026-09-05 15:00');
      expect(formatShanghaiDateTime('2026-09-05T07:00:00')).assertEqual('2026-09-05 15:00');
      expect(formatShanghaiTime('2026-09-05T07:00:00Z')).assertEqual('15:00');
      expect(formatShanghaiRange('2026-09-05T07:00:00Z', '2026-09-05T08:30:00Z'))
        .assertEqual('2026-09-05 15:00–16:30');
      expect(formatShanghaiRange('2026-09-05T15:30:00Z', '2026-09-05T17:00:00Z'))
        .assertEqual('2026-09-05 23:30–09-06 01:00');
      expect(formatScenicClock('09:00:00')).assertEqual('09:00');
      expect(formatShanghaiDateTime('not-a-time')).assertEqual('时间待定');
    });
  });
}
