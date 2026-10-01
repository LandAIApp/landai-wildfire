# Project documentation

This scaffold reserves the following responsibilities for later implementation:

| Directory | Intended responsibility |
| --- | --- |
| `backend/app/api/` | HTTP routes |
| `backend/app/core/` | Application configuration |
| `backend/app/schemas/` | Request and response models |
| `backend/app/services/` | Integration and orchestration |
| `backend/app/wildfire/` | Future Earth Engine algorithm migration |
| `backend/tests/` | Future tests |
| `notebooks/` | Future exploratory notebooks |

Empty `.gitkeep` files retain reserved directories. The [spectral module](spectral-indices.md) and the [historical module](historical-variability.md), with their offline tests, are now implemented. No classification,
algorithm changes, database, authentication, or frontend are introduced.

## Reference provenance

The authoritative source is `../wildfire_gee_reference.js`, FIRE FOREST COLOMBIA
V7.6. Its SHA-256 at scaffolding time is:

```text
09B91DE8F89A3000CA4C741C64905F1FF766FB42EB237EF0C55F465211A25A3A
```

The supplied GEE attachment is byte-identical to this source. The source remains
at its original root location; `reference/wildfire_gee_reference.js` was absent.

[Supplied analysis](wildfire_gee_analysis.md) is an unmodified copy of the user's
analysis attachment, retained as supporting context rather than a replacement for
the JavaScript. Its proposed migration work is deferred. Statements about prior
validation data in that attachment do not establish that such data is present here.

The reference combines PRE/POST Sentinel-2, historical context, agricultural
evidence, VIIRS, dynamically generated training samples, Random Forest, and spatial
cleanup. The JavaScript contains no `Export.*` calls and loads no validation
polygon asset, despite broader descriptions in the original reference notes.

Future equivalence specifications, API contracts, and validation plans remain to
be written. No scientific execution or Earth Engine validation was performed in
this scaffolding step.
