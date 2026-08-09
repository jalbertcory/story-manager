# Application lifecycles

Story Manager's persisted lifecycle vocabulary is defined in `backend/app/lifecycle.py`. That module owns allowed values, transitions, labels, active and terminal groupings, retryability, and recovery targets. The `GET /api/lifecycles` endpoint exposes the same manifest to the frontend; UI code must not maintain a second list of lifecycle labels or groupings.

Database check constraints reject unknown persisted values. They deliberately validate values rather than transition edges: application helpers enforce edges while migrations and recovery routines can safely repair rows in bulk.

## Transition rules

Services should call `transition_state(record, attribute, machine, target)` for ORM-backed changes and use the lifecycle enums for bulk updates. Invalid edges raise `InvalidStateTransition` with the lifecycle name, current and requested values, context, and allowed targets.

Assigning the current value again is allowed. This makes idempotent retries safe without weakening the set of possible next states.

## Recovery contract

| Lifecycle | Non-terminal state | Recovery behavior |
| --- | --- | --- |
| Processing job | `queued` | Remains available until a worker for its resource lane claims it. |
| Processing job | `running` | An expired lease is atomically reclaimed and returned to `queued`, subject to the attempt limit. |
| Web import | `pending` | The durable import processing job is resumed or retried; the placeholder remains visible. |
| Web refresh | `queued` | The durable refresh processing job remains claimable. |
| Web refresh | `processing` | The processing-job lease is reclaimed; refresh returns to `queued` before retry. |
| Library refresh task | `running` | Startup reconciliation marks the historical task `interrupted`; incomplete book refresh jobs remain independently recoverable. |
| Metadata job | `queued` | Remains claimable by the metadata resource lane. |
| Metadata job | `running` | Reconciliation returns it to `queued` when its processing job is reclaimed. |
| Generated audiobook pipeline | Any phase from `ingesting` through `assembling` | The durable processing job resumes from the persisted phase and artifacts. The phase is not guessed from process memory. |
| Audiobook publication | `processing` | Interrupted packaging is marked `stale`; reconciliation rebuilds from durable chapter artifacts. |
| Chapter preview | `queued` | Remains claimable as a processing job. |
| Chapter preview | `generating` | Recovery returns it to `queued`. |
| Published chapter | `pending` | Packaging reconciliation processes it. |
| Published chapter | `processing` | Recovery returns it to `pending`. |
| Sentence | `pending_diarization` | The next diarization pass resumes it. |
| Sentence | `audio_queued` or `audio_generating` | Recovery returns it to `ready_for_audio`; a full run, preview, or explicit sentence request can queue it again. |
| Imported audiobook | `queued` | Remains claimable by the import resource lane. |
| Imported audiobook | `importing` | Recovery returns it to `queued`. |
| Imported audiobook | `aligning` | Recovery returns it to `ready`; the existing edition remains usable and alignment can be requested again. |
| Imported audiobook | `stale` | Reconciliation reimports or rematches it from its retained source files. |

The manifest's `recovery` field is the machine-readable summary of these targets. Some waiting states recover to themselves because their durable job is the recovery mechanism.

## Parent and child jobs

A processing job may enqueue child jobs by setting `parent_job_id`. Parent and child records have independent leases, attempts, cancellation flags, progress, and terminal states:

- A parent may complete after dispatching children; completion does not imply that every child succeeded.
- A child failure is visible and retryable on its own. It does not rewrite a completed parent.
- Retrying or canceling a parent does not implicitly cascade to children. A workflow that needs cascading behavior must request it explicitly and transition every affected job.
- Dedupe keys and target content versions prevent a recovered parent from creating duplicate current-version children.

This separation keeps fan-out work observable and recoverable without pretending it is one in-memory transaction.

## Adding or changing a lifecycle

1. Add or update the enum and `StateMachine` in `backend/app/lifecycle.py`.
2. Route service changes through `transition_state` or enum-backed bulk updates.
3. Add a safe Alembic migration for persisted values and constraints; normalize existing data before adding a constraint.
4. Use `/api/lifecycles` for frontend labels and behavioral groupings.
5. Add transition, recovery, populated-database migration, and affected workflow tests.
