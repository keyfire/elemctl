# Origin

elemctl is an independent, **clean-room** implementation, written from scratch.

## What it is built from

- a written specification of the platform's external interface (`docs/SPEC.md`), which
  records **facts about the 1C:Enterprise.Element (1cmycloud) Console API v2 contract**,
  the build-file formats (`.xasm` / `.xlib`) and the product requirements – and nothing
  else, and
- the **Python standard library**.

The API facts in the specification come from three first-hand sources:

1. **The platform's own Console API reference** – the Element help shipped by the
   platform itself, with a page per endpoint (e.g. `POST /console/api/v2/applications`),
   under <https://1cmycloud.com/console/help/element/9.2/docs/console/>. The help is
   provided to platform users; at the time of writing it opens after signing in with a
   platform account.
2. **The management console UI**, which every platform user has access to.
3. **Observation of the author's own requests and responses** while using the platform
   under the author's own account. This covers behavioral details the reference does not
   describe (e.g. the silent rollback on a failed project update).

No documentation beyond what the platform provides to its users was used. The tool talks
only to the documented Console API v2; internal (undocumented) console APIs are neither
called nor described anywhere in this repository.

No other tool's source code was read or copied. The implementation was designed from the
specification alone.

## What is definitely NOT in it

- **No third-party source code.** Nothing was ported or copied from any other
  repository – public, private or corporate.
- **No platform code.** No decompilation, disassembly or other reverse engineering of
  1C:Enterprise.Element components was performed; the platform's own client or server
  code was never used or examined.
- **No reproduced proprietary materials.** The platform vendor's documentation and other
  materials are not quoted or reproduced.
- **No secrets and no ties to anyone's infrastructure.** The code and the git history
  contain no tokens, passwords, internal addresses, or identifiers of specific
  applications, projects or stands.

## Credentials and runtime

Access to the platform uses `Client-Id` / `Client-Secret` credentials that the platform
issues to its own users in its management console. elemctl ships no credentials and
redistributes nothing belonging to the platform.

At runtime the library depends only on the Python standard library. The MCP server is an
optional extra (`elemctl[mcp]`) and uses the `mcp` package (its ergonomic server class:
`FastMCP` in mcp 1.x, `MCPServer` in mcp 2.x).
