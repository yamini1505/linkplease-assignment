# Known Failure Modes

This document lists the known limitations and failure modes of the current implementation.

- If the application process stops while a webhook is being processed in FastAPI's in-memory `BackgroundTasks`, the event may not finish processing. The webhook has already returned `200`, but there is no persistent job queue recording the unfinished background task.

- If two duplicate webhook events for the same rule and user are processed at exactly the same time, both workers could potentially pass the duplicate check before either transaction commits. The database unique constraint on `(rule_id, user_id)` provides protection at the database level, but the application does not currently implement a full transaction/retry strategy for this race.

- The current implementation sends a DM and then records the delivery in the database. If the DM API accepts the request but the application crashes before the database record is committed, the next webhook could attempt the DM again. The Idempotency-Key sent to the mock API reduces the risk of an actual duplicate DM, but the local database may not immediately reflect the accepted delivery.

- The mock API can return `202 Accepted` even though the DM later fails. The reconciliation worker checks accepted DM IDs and updates their local status, but the current retry strategy is limited and may eventually leave a failed delivery without another retry.

- The current statistics are calculated from the local database. During heavy concurrent processing, there can be a short period where the database has not yet reflected the latest webhook or delivery status, so `/stats` may temporarily differ from the mock API's server-side truth.

- The current application uses SQLite. It is suitable for this assignment and local testing, but it is not the ideal database for millions of monthly events or high-concurrency production workloads.

- The webhook signature verification depends on the configured PseudoGram API key. If the key is missing or incorrect in the deployment environment, legitimate webhook requests will be rejected.

- `comment.deleted` events are not currently used to cancel an already queued delivery. A production implementation would persist event state and decide whether a pending delivery should be cancelled when its source comment is deleted.