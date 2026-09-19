# Example: evidence request instead of guessing

This illustrative case is not evidence from a real repository.

## Stable brief

Intent: change. Goal: fix an intermittent login failure after refresh.
Constraints: preserve the public sign-in API and session format; no new
dependency; no deployment authorized. Success requires reproduction, a targeted
regression test, and existing authentication checks.

## Decision evidence

- The failure occurs after refresh, not initial login.
- The supplied excerpt shows login calling refresh and then updating a cache.
- The exact failing-test output identifies stale cached session identity.
- The cache-key function and its callers have not yet been supplied.
- “The cache identity uses old expiry” is a hypothesis, not an observed fact.

## Decision objective

Which bounded fix addresses the refresh failure without breaking session reuse?

## Appropriate ASTRA response

REQUEST_EVIDENCE: request the cache-key function, refresh return shape, affected
callers, and the failing assertion, with reasons tied to the decision. Do not
invent the missing implementation or author a patch.

LUNA returns those exact excerpts and current evidence. ASTRA then proposes a
fix, defines ACs and verification, and the controller pauses in a plan gate for
the user to approve. Only after approval does LUNA implement. SOL later reviews
the fresh result and either returns `DONE` or a bounded transition. A later
packet retains the stable constraints and includes the new diff/test results,
not a second copy of all earlier logs.
