<!-- SPDX-License-Identifier: Apache-2.0 -->

# Licensing

This document describes the proposed license scope for Grider. The complete
license texts are in [`LICENSES/`](LICENSES/).

## Scope

| Files | License |
| --- | --- |
| `rtl/**`, `docs/architecture.md`, `docs/isa.md` | CERN-OHL-W-2.0 |
| All other project-authored tracked files, including `grider/**`, `tests/**`, `scripts/**`, `.github/**`, `Makefile`, `pyproject.toml`, `README.md`, `TODO.md`, and `docs/synthesis.md` | Apache-2.0 |

File-level SPDX identifiers follow this mapping. The files in `LICENSES/`
contain license texts and third-party notices; they are not additional Grider
design or software source.

## CERN-OHL-W-2.0

The CERN-OHL-W-2.0 terms apply to the Covered Source identified above. When a
modified Covered Source is conveyed, the license requires applicable notices,
a dated modification notice with a brief description, and licensing of that
modified Covered Source under CERN-OHL-W-2.0. When a Product is conveyed, the
recipient must receive the Complete Source or be notified of its Source
Location, subject to the license terms and its Available Component and External
Material provisions. See the full text in
[`LICENSES/CERN-OHL-W-2.0.txt`](LICENSES/CERN-OHL-W-2.0.txt).

An independently developed design connected to Covered Source through a
documented interface is not automatically Covered Source. The license's
definition of External Material and all other terms in its full text govern.

## Apache-2.0

The Apache-2.0 terms apply to the software, tests, development tools, project
documentation, and configuration files listed above. See the full text in
[`LICENSES/Apache-2.0.txt`](LICENSES/Apache-2.0.txt).

## Third-party materials and generated files

The tracked source tree contains no vendored third-party source identified by
the repository review. CI downloads a pinned SkyWater timing library under
Apache-2.0 for synthesis; that input remains under its upstream license and is
not checked into this repository or included in the workflow artifact.

CI also installs the pinned SRAM22 generator, whose source is under BSD
3-Clause, and uploads generated SRAM macro views as a workflow artifact. Those
generated views are not tracked in Git and are not relicensed by this document.
The accompanying notice records the generator's provenance; it does not
assert that the generator's source license determines the license of every
generated view. Review the upstream terms and applicable PDK rights before
redistributing those views outside the CI artifact. Build products are ignored
by `.gitignore`.

EDA tools and GitHub Actions used by CI are external dependencies and are not
included in the Grider source license scope.

## Copyright-holder review

This draft does not assert a copyright holder in file-level notices. The
available Git history is not sufficient evidence of legal ownership or
authority to license every contribution. Before merging this licensing
change, maintainers must confirm the copyright holder(s) and authority to apply
these terms, including any contributions not owned by the project maintainer.
