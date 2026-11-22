# Constitution (immutable principles)

These are the non-negotiable principles of this project's harness. Amendments require a logged
decision in `.harness/archive/decisions/`.

1. **Fail closed on the critical path.** Commit / push / verify gates refuse on failure. They never
   log-and-continue. If enforcement can't run, that is a failure, not a skip.
2. **Test-first (TDD).** New behavior is accompanied by a test that fails before and passes after.
   Verification proves behavior, not file presence.
3. **Ground every claim.** Plans cite `path:line`; unresolvable citations fail. Verification abstains
   (`human_needed`) rather than silently passing.
4. **Zero hardcoded couplings.** Every stack/host/repo specific is a named config key. No absolute
   paths, no hardcoded branch or project names in portable code.
5. **Memory lives in-repo.** Durable context is committed, not host-local.
6. **Overrides are accountable.** Any escape hatch appends a justified decision-log entry.
