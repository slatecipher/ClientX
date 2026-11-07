# Security Policy

## Supported versions

ClientX is pre-1.0. Security fixes go into the latest release only, so upgrade to the newest version to receive them.

## Reporting a vulnerability

**Please don't report security vulnerabilities in public issues, pull requests, or discussions.**

Report them privately through GitHub instead:

1. Go to the repository's [Security tab](https://github.com/slatecipher/ClientX/security).
2. Click **Report a vulnerability**.
3. Describe the problem: which versions are affected, how to reproduce it, and what an attacker could do with it.

Only the maintainer can see the report. ClientX is maintained in spare time, but security reports take priority over other work.

## What happens next

1. The maintainer confirms whether the report is a vulnerability and works on a fix, keeping you updated in the report.
2. The fix is released as a new version.
3. A GitHub security advisory is published, crediting you unless you'd rather stay anonymous.

Please keep the details private until the advisory is published.

## Scope

This policy covers ClientX itself. Report vulnerabilities in its dependencies, such as `httpx2` or `pydantic`, to those projects directly.
