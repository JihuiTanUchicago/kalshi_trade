# Independent functional review and guard restoration

Initial read-only reviewer reproduced two P2 navigation regressions in the port: System and Billing initial responses could outlive their route, dereference removed controls and let the departed render replace the active page with an error. Further shipped-guard comparison found Funds post-write and Admin/operator continuation guards also need preservation. These were not detected by the initially passing77 workspace/8current-behavior cases.

Root delegated exclusive app.meridian.js and test_meridian_workspace.mjs ownership for narrowly restoring the shipped S.gen guards/error behavior and adding meaningful failing-before/passing-after tests. Default assets, API payloads, financial validation/eligibility and compact layout remain no-touch. Source publication is held until fixes, tests and review pass. No production changes or new design iteration occurred.

## Corrected and verified before publication

Shipped generation/error guards were restored in Funds, Billing, Admin and System, preserving exact endpoints, payloads, financial validation and compact layout. Twenty-two new regressions retain the original77Meridian cases; the unfixed baseline recorded21failures. Fixed99/99Meridian+8/8current behavior pass. Root read the entire guard delta; final178frontend/full1676Python/10skipped/syntax/whitespace pass. Final native Dashboard loaded d898ab44/0cf54995 with no overflow or false update; actual production font200 matches source. No code is deployed yet.
