# NSW address records (G-NAF)

Property search and every property record come from G-NAF, the Geocoded National Address File published by Geoscape Australia. PropertyScope loads the NSW part of each quarterly release.

## What one record is

A property record is one registered address with its structured parts (unit or shop number, street number, street name and type, locality, postcode), coordinates and G-NAF identifiers. A building with many units or shops has one record per registered address, so "1 Macquarie Street" and "Shop 12/1 Macquarie Street" are separate records.

An address record is not a title, a legal lot, a dwelling count, an owner or a valuation. Counts of property records for a suburb or postcode are counts of registered addresses, not houses.

## Identity status

Each record has a PropertyScope reference that stays the same across releases. "Verified" means the address came from the published G-NAF release and its source identifiers were checked. The Sources and identifiers tab lists those identifiers and any address aliases.

## Why an address might not be found

- The address is newer than the loaded G-NAF release. New subdivisions can take one or more quarters to appear.
- The address is written differently, for example "Rd" for "Road" or a unit written as "U5". Try the street and suburb without the number.
- The place has no registered street address, such as some rural lots.
- No G-NAF release has been published on this installation. Check Published data.

A search with no result is not evidence that a property does not exist.

## Licence

G-NAF is used under its end-user licence. PropertyScope serves address search and property records from it, but the bulk release file cannot be downloaded from PropertyScope.
