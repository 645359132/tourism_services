import dateTimeRulesTest from './DateTimeUnit.test';
import tourismBusinessRulesTest from './LocalUnit.test';

export default function testsuite() {
  tourismBusinessRulesTest();
  dateTimeRulesTest();
}
