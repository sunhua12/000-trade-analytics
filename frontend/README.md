# 美國半導體進口分析

A static, dependency-free semiconductor trade observatory. Uses a verified UN Comtrade JSON snapshot; no cloud credentials or backend services are required by visitors.

```bash
node --test frontend/tests/*.test.mjs
node frontend/build.mjs
node frontend/serve.mjs
```

When this directory is checked out independently, omit the `frontend/` prefix. Requires Node 22 or newer. Local preview: http://127.0.0.1:4173.

The parent repository owns the Python/dbt pipeline. Refresh the public snapshot from the repository root with `trade-export --snapshot-root data/frontend-v2 --stage-data frontend/public/data`, then build and publish the entire website as one version. `public/data/` contains only the three validated public files. Do not copy audit records, dbt artifacts, environment files or cloud credentials into this project.

Frontend aggregation uses BigInt fixed-point NUMERIC arithmetic; charts alone convert values to Number. Date/country filters, World denominators, Top N, YoY and HHI follow the parent project's frontend data contract. CSV exports the complete date/country scope, rather than the displayed Top N or table page.

Design: Apple/Notion-inspired spacing, quiet surfaces and structured navigation; Design Taste informed typography, restrained color and motion. Better Design's MCP is not connected; no MCP review or theme installation is claimed. See the parent project's design decisions for reference links.

Map geometry is public-domain Natural Earth data; see `assets/NOTICE.md`.

## Data delivery and loading performance

The build verifies the original public snapshot, then generates lossless column-array
JSON compressed with gzip: one monthly file and one complete partner file per importing
market. Content hashes in filenames allow browser caching; the generated manifest
records each compressed file's bytes, SHA-256, row count, encoding and snapshot version.
The browser verifies compressed bytes before decompression and checks the restored
snapshot before showing results. This requires a browser with `DecompressionStream`
(current Chrome, Firefox, Edge and Safari). Original snapshot files remain available
for audit and older clients; they are not downloaded by the optimized homepage.

The homepage downloads monthly data and the default US market only. Other markets load
on selection and are reused for the session. Failed requests can be retried and downloads
have a 30-second timeout. Market switches hide stale results and ignore superseded
responses. Exact NUMERIC strings, nulls, row ordering and complete filtered CSV exports
are preserved. Analysis is reused when only the page, language or window size changes;
detail-table sorting is deferred until the data page is opened.

With snapshot `65e478c3765d4c3f836115b1f5b5e529`, initial analytical data drops from
76,022,488 bytes to 1,131,833 bytes (98.5% smaller), excluding unchanged map/UI assets.
These are payload sizes, not a guarantee about load time on every connection.
`tests/delivery-production.test.mjs` verifies every production market's restored rows,
KPI/trends/rankings and full CSV against the original snapshot, plus the size budget.

Current preview uses a compact dark layout, a single-line title and six dashboard panels in a two-column desktop grid. No custom branding, logo or top information bar is displayed. HHI remains in the data contract but is omitted from the UI; country coverage remains visible. Detail pages show 50 compact rows.
