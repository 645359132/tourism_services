import dateTimeRulesTest from './DateTimeUnit.test';
import itineraryExperienceRegressionTest from './ItineraryExperienceRegression.test';
import tourismBusinessRulesTest from './LocalUnit.test';

export default function testsuite() {
  tourismBusinessRulesTest();
  dateTimeRulesTest();
  itineraryExperienceRegressionTest();
}
