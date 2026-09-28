# How sales are attributed to a property and how confident that is

A sale record is linked to a property by matching the address in the source record against the
verified property you selected. That match is not always exact, so each sale carries a match tier
and a match confidence describing how sure the attribution is.

## Match tiers and the threshold

Tier A is the strictest attribution and the most confident; lower tiers admit progressively looser
address matches. Each case carries a minimum match tier, defaulting to tier B, and any sale below
that tier is excluded from the summary and counted under the below-threshold exclusion reason.

Raising the threshold to tier A gives you the sales most confidently attributed to the property,
at the cost of a smaller sample. Lowering it admits more records, some of which may belong to a
neighbouring or similarly named address. The tier describes confidence in the address match only.
It says nothing about whether the price is representative or the sale was at arm's length.

## Reading a summary honestly

The eligible sale count and the excluded count should be read together. A median drawn from three
eligible sales with twelve excluded is a much weaker statement than the same median drawn from
thirty, and the summary reports both so the difference stays visible.

Volume by contract year shows when the eligible sales occurred. Gaps in that series mean no
eligible sale was registered in those years for this property at this threshold. They do not mean
the property was unavailable, unsold or unoccupied, and they are not evidence of market conditions
in the wider area.
