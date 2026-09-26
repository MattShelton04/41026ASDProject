# Crime data coverage

Property data loads the NSW Bureau of Crime Statistics and Research (BOCSAR) recorded crime archives. They give monthly counts of recorded offences by offence category for each postcode and each suburb, from 1995 onwards.

## Zero, blank and unavailable

The dataset stores months that had recorded offences, plus the exact list of months each series covers. A covered month with no stored count means zero recorded offences only when the series is marked as treating blanks as zero; otherwise its value is unknown. A month outside the covered list is unavailable, not zero.

Recorded crime counts offences reported to and recorded by police. A zero does not mean no crime happened, and a missing month says nothing either way.

## What Property data does not do

Property data does not calculate crime rates, rank suburbs by safety or predict crime. The Suburb context research area imports this data and owns that analysis. When describing crime data, state the geography (postcode or suburb), the period and the offence category.
