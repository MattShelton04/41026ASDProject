# How other research areas receive data

Other research areas do not read Property data's database. They receive published versions over HTTP and import them into their own databases.

## The import

A receiving feature downloads the release file, then checks its size, SHA-256 checksum, compression, record format, schema and record count before loading it in one step. It can find the record schemas through the product-contracts endpoint instead of reading repository files.

## Independent timing

Publishing in Property data and importing in another feature are separate. A version can be published and downloadable while a downstream import is still pending or has failed. To know whether a feature has the new data, check that feature's import status or receipt, not the publication status.

## Current deliveries

Sales history goes to Sales and market. Crime data and school locations go to Suburb context. Other datasets are currently used only within Property data.
