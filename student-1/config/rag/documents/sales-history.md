# NSW property sales (PSI)

Sale history comes from the NSW Valuer General's property sales information (PSI). PropertyScope loads the annual archives from 1990 and the weekly files for the current year, and keeps each source row as published.

## What a sale record contains

Each record keeps the contract date, settlement date, purchase price in dollars, land area, zoning, nature of property, primary purpose, strata lot number and the Valuer General's district and property identifiers. Dates and prices can be blank in the source. About 2% of pre-2001 records show a price of $0; this is how the source recorded them, not a free transfer.

When the same sale is sent again unchanged it is stored once. When a sale is corrected in a later file, both versions are kept in order.

## How sales are matched to a property

A sale is linked to a property record only when its address resolves to exactly one published G-NAF address. The match is shown with its method and confidence on the Sale history tab. If the address is ambiguous or not found, the sale is kept but left unmatched rather than guessed.

Matching is incomplete. In the September 2026 load, about 69% of post-2001 sale records and 54% of pre-2001 records matched a single address. Unit sales and older records written in free-text address formats are the most likely to stay unmatched.

An empty Sale history tab means no matched sale was found in the published sales data. It does not mean the property has never sold: the sale may be unmatched, older than 1990, or not yet published.

## Partial year ranges

A sales update normally loads the complete history. An update limited to selected archive years produces a partial version that can be inspected but cannot be published. See "Selected PSI archive years are partial".

## Analysis belongs to Sales and market

Property data supplies the sale records. Medians, trends, comparable sales and valuations belong to the Sales and market research area.
