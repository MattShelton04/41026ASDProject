# Geometry-free locality evidence for the assistant

## Generated projection

The optional generated corpus projection uses accepted ABS 2021 statistical-locality and LGA polygons plus accepted NSW facility points. Geometry is used transiently to associate records, then omitted from the assistant document. Each generated document identifies the accepted release IDs and retrieval dates that produced it.

## Locality and LGA meaning

An ABS statistical locality is not necessarily a current gazetted suburb. A representative point falling within an LGA polygon is a deterministic association, not an official suburb-to-LGA crosswalk. Locality and LGA boundaries can differ, overlap or change between editions. The assistant must repeat that limitation when an LGA relationship matters to the answer.

## Refresh and absence

Generated documents are a snapshot of the accepted releases used at build time. Rebuild and reingest them after either source release changes. A missing generated locality or amenity category means the corpus lacks supporting context; it does not establish that the locality or facility does not exist.
