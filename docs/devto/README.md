# DEV.to publishing - ARE SoftwareGPU only

This repository publishes **only to DEV.to**. It does not send content to Bluesky, X, Discord, Medium, or other networks. The initial article is technical, verifiable, and explicitly AI-assisted; it is not a promotional backlink dump.

## Setup (owner action required)

1. In DEV.to settings, revoke the API token previously posted in a conversation and issue a fresh token.
2. In the GitHub repository, visit **Settings -> Secrets and variables -> Actions -> New repository secret**. Name it `DEVTO_API_KEY` and paste the new token into the secret value. Never add it to code, PRs, issues, or workflow logs.
3. Review `cpu-rendering-evidence.md` for facts, measurements, current links, disclosures, and the PolyForm Noncommercial 1.0.0 license classification.
4. Merge the reviewed Draft PR only after its tests and CI gates pass. A change to `docs/devto/**` on `main` runs the publisher, which creates or updates a **draft** on DEV.to.
5. To publish publicly, open **Actions -> DEV.to technical article -> Run workflow**, select branch `main`, set `publish` to **true**, and launch it. The manual switch allows public publication after human review.

## Behavior and safety

- The publisher uses standard-library Python and DEV.to's authenticated `/api/articles/me/all`, `POST /api/articles`, and `PUT /api/articles/{id}` endpoints.
- The canonical URL is the reviewed Markdown source in GitHub. It is used to discover and update the existing article rather than create duplicates. Ambiguous matches fail closed.
- A routine push never switches a published article back to draft. Public publication requires an explicit manual boolean on GitHub Actions.
- Missing secrets, malformed metadata, frontmatter attempts to override `published`, API errors, and duplicate identities fail closed. The API key is never printed.
- The check command has **no external API side effects**: `python tools/devto_publish.py --check`.
- Offline real-HTTP regression checks: `python -m unittest discover -s software_gpu/tests -p test_devto_publish.py -v`.
- An Actions run or local test does not prove an article was published. Verify the resulting DEV.to draft/article URL before claiming it is public.

DEV.to publishing must follow [DEV Community's AI content rules](https://dev.to/guidelines-for-ai-assisted-articles-on-dev/) and non-spam guidelines. Review the article as technical education rather than marketing. Benchmarks are CPU-versus-CPU, not GPU parity or production guarantees. The software license is source-available and noncommercial, not OSI open-source.
