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

Current preview uses a compact dark layout, a single-line title and six dashboard panels in a two-column desktop grid. No custom branding, logo or top information bar is displayed. HHI remains in the data contract but is omitted from the UI; country coverage remains visible. Detail pages show 50 compact rows.
