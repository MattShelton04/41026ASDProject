# Shared browser primitives

This package is the stable, domain-neutral browser surface used by the Shared shell and copied or
mounted into Feature 1. `request.js` owns timeout and abort-signal composition for Shared HTTP
clients. Route controllers must destroy or abort their work when the user navigates away.

Only HTML entry scripts carry a deployment cache revision. Internal ES module imports use their
canonical query-free URL so every module is instantiated once instead of creating parallel module
graphs for different `?v=` values.

