# Accepted addresses and ambiguous discovery

Property Discovery resolves NSW addresses against the current published property register. Candidate data is isolated from accepted property search; the accepted pointer selects the immutable generation used for reads. A successful candidate import is not publication.

PSI exact-address matching uses the accepted G-NAF generation and recognised street-type equivalents. Unique matches create missing registry reference anchors; canonical address fields still come from the accepted warehouse generation. Do not choose an address silently when evidence is ambiguous, or treat an unmatched sale's nullable property_ref as proof that the sale did not happen. Retain the source facts and report the unresolved link.

Basis: student-1 README; ADR-038, accepted G-NAF reference anchors; data-product consumer guide, sales semantics. Guidance does not resolve a specific query without current property evidence.
