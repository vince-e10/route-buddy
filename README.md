# Route Buddy

Route Buddy finds, compares, books, tracks, and cancels Singapore rides. The MVP uses a
deterministic mock of Uber Guest Rides, never the real Uber API.

```
                    docker compose up  (one command)
 +-----------------------------------------------------------------+
 | Browser <--(WebSocket: chat + confirms + live status)--+       |
 | (static chat page served by api)                       v       |
 |  +---------+ terraform apply  +------------------------------+ |
 |  | iac     |----------------->|          api (FastAPI)       | |
 |  | (init,  |                  | agent loop + tools + gate    | |
 |  | exits)  |                  | action log + sessions + WS   | |
 |  +----+----+                  +---+-----------+--------------+ |
 |       | creates tables            |           ^                |
 |       v                           v           | webhook        |
 |  +------------+             +------------+   | (status_changed|
 |  | floci      |<------------| mock-uber  |---+  + shared      |
 |  | DynamoDB   |  (no - api  | (FastAPI)  |      secret)       |
 |  | 4 tables   |  only)      | Guest Rides|                    |
 |  +------------+             | + driver   |                    |
 |                               | simulator  |                    |
 |                               +------------+                    |
 +-----------------------+---------------------+-------------------+
                         v external            v external
                  OpenRouter API         SG OneMap API
             (glm-4.5-air -> minimax-m2) (geocoding, token)
```

## Prerequisites and environment

Install Docker Desktop with Compose v2. Copy `.env.example` to `.env`; it is gitignored. Do not
commit values or put secrets in chat. The local mock works with the documented mock defaults;
real OpenRouter and OneMap values are needed for the non-fake demo path.

| Variable | Obtain or set it from |
| --- | --- |
| `OPENROUTER_API_KEY` | An [OpenRouter API key](https://openrouter.ai/keys). |
| `OPENROUTER_BASE_URL` | The documented OpenRouter base URL in `.env.example`. |
| `OPENROUTER_MODEL_PRIMARY` | The approved primary model in `.env.example`. |
| `OPENROUTER_MODEL_FALLBACK` | The approved fallback model in `.env.example`. |
| `LLM_MODE` | `openrouter` for normal use or `fake` for deterministic tests. |
| `FLOCI_STORAGE_MODE` | `persistent` locally or `memory` for disposable CI runs. |
| `FLOCI_STORAGE_PERSISTENT_PATH` | The documented Floci container path in `.env.example`. |
| `AWS_ENDPOINT_URL` | The Compose Floci endpoint in `.env.example`. |
| `AWS_ACCESS_KEY_ID` | The local Floci test credential in `.env.example`. |
| `AWS_SECRET_ACCESS_KEY` | The local Floci test credential in `.env.example`. |
| `AWS_DEFAULT_REGION` | The Singapore region in `.env.example`. |
| `UBER_BASE_URL` | The Compose mock-Uber endpoint in `.env.example`. |
| `UBER_API_TOKEN` | The static MVP mock token in `.env.example`. |
| `UBER_ORG_UUID` | The static MVP mock organization id in `.env.example`. |
| `WEBHOOK_SHARED_SECRET` | A locally generated secret used by API and mock-Uber only. |
| `ONEMAP_BASE_URL` | The OneMap API base URL in `.env.example`. |
| `ONEMAP_EMAIL` | The email for your [OneMap account](https://www.onemap.gov.sg/home/). |
| `ONEMAP_PASSWORD` | The password for that OneMap account. |
| `RIDER_FIRST_NAME` | The local MVP rider's first name. |
| `RIDER_LAST_NAME` | The local MVP rider's last name. |
| `RIDER_PHONE` | The local MVP rider's E.164 phone number. |
| `SIM_SPEED` | Lifecycle speed multiplier; keep the documented default unless demoing. |
| `MOCK_DETERMINISTIC` | `1` for deterministic tests, otherwise `0`. |
| `WEBHOOK_TARGET_URL` | The Compose API webhook URL in `.env.example`. |

## Run and demo

```sh
cp .env.example .env
# Edit .env locally with the values above.
docker compose up -d --build
```

Open `http://localhost:8000`, or use the bounded startup helper:

```sh
./scripts/demo.sh
```

Example conversation:

1. `Take me from Changi Airport to Marina Bay Sands`
2. Select the exact quote card, then click Confirm on the booking card.
3. Select cancellation on the exact active-trip card, then click Confirm.

## Tests

The release gate starts a disposable deterministic stack, runs all API, live WebSocket, security,
and mock-Uber tests, then always removes containers and volumes.

```sh
./scripts/e2e.sh
```

For focused checks against an already running stack:

```sh
docker compose exec -T api python -m pytest tests -v
docker compose run --rm --no-deps -v "$PWD/mock-uber/tests:/tests:ro" mock-uber python -m pytest /tests -v
```

The live-model reliability evaluation uses the production OpenRouter request path but never
starts dependencies or executes a returned tool call. Configure the OpenRouter key through the
existing local environment flow, then run both configured models three times:

```sh
docker compose run --rm --no-deps --build -v /tmp:/reports api \
  python -m evals.tool_call_reliability \
  --model primary --model fallback --runs 3 \
  --output /reports/route-buddy-tool-call-report.json
```

The machine-readable report is written to `/tmp/route-buddy-tool-call-report.json` on the host.
The `primary` and `fallback` aliases resolve from the configured model variables. This live
evaluation is intentionally excluded from CI. It exposes the same four read-only tools as
production and retires the old model write-proposal cases.

## Architecture and invariants

- Every book or cancel requires a fresh, single-use user confirmation.
- The DynamoDB action log is append-only and records requested, verified, executed, and outcome phases.
- Prices, ETAs, identifiers, and lifecycle state come from tool output, never model invention.
- The model never receives rider PII. The API adds it only while executing a confirmed booking.

The model has read-only tools. Booking and cancellation start only from exact structured-card
selections, then require confirmation of the server-frozen action.

Only four read tools and state-legal IDs are sent to the model. Calls are sequential, and one
structurally invalid primary proposal may receive one correction pinned to the fallback model.
The fallback is subject to the same validation. Invalid argument text in the audit log is capped
at 512 characters.

## AWS demo simulation

No AWS account is required for the current project. `infra/aws` is a simulated deployment
definition: CI validates it with Terraform's mocked AWS provider, while application behavior is
verified against the local Floci stack.

Run the offline checks only:

```sh
terraform -chdir=infra/aws init -backend=false -input=false
terraform -chdir=infra/aws validate
terraform -chdir=infra/aws test
./scripts/e2e.sh
```

Do not run the bootstrap, create GitHub Environments, populate Secrets Manager, or run an AWS
plan/apply. The deployment note in [PR #38](https://github.com/vince-e10/route-buddy/pull/38)
is a future live-AWS acceptance path, not a requirement for the simulated demo.

The simulation covers this intended shape:

```text
Route53 -> ACM HTTPS -> public ALB
                            |
                   one private Fargate task
                   +-------------------------------+
                   | api :8000                     |
                   | mock-uber :8001 via localhost |
                   +---------------+---------------+
                                   |
                          four DynamoDB tables
```

It does not prove AWS IAM authorization, service quotas, provider behavior, or successful
creation of live resources.

## AWS bootstrap (future live AWS only)

`infra/bootstrap` creates only the AWS trust and artifact foundation: the Terraform state bucket,
GitHub OIDC provider, separate bootstrap and demo deployment roles, runtime-role permissions
boundary, and private ECR repositories. It does not create application runtime resources.

Everything in this section is deferred until the project has an AWS account and explicitly
chooses to perform a live deployment.

The implementation follows guidance accessed on 2026-07-27:
[GitHub OIDC for AWS](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws),
[GitHub deployment Environments](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments),
[AWS GitHub OIDC trust](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_create_for-idp_oidc.html),
[Terraform S3 locking](https://developer.hashicorp.com/terraform/language/backend/s3), and
[ECR tag immutability](https://docs.aws.amazon.com/AmazonECR/latest/userguide/image-tag-mutability.html).

### GitHub prerequisites

Before the first workflow run:

1. Create `aws-bootstrap` and `aws-demo` GitHub Environments.
2. Restrict both to protected `main`. Configure a required reviewer and prevent self-review when
   the repository plan supports it.
3. Set non-secret Environment variables `AWS_ACCOUNT_ID` and `AWS_REGION`.
4. If the AWS account already has the GitHub OIDC provider, set `OIDC_PROVIDER_ARN` in
   `aws-bootstrap`; otherwise leave it unset.
5. Set `ROUTE53_HOSTED_ZONE_ID` only after the later AWS demo zone is selected.

Do not add AWS access keys or application secret values to GitHub.

### First bootstrap and state migration

An AWS administrator performs this once from an out-of-band authenticated session. Use exactly
Terraform 1.15.8. Never paste credentials into chat, issues, variables, or workflow inputs.

```sh
export TF_VAR_aws_account_id="<12-digit account id>"
export TF_VAR_aws_region="ap-southeast-1"
# Only when adopting the account's existing GitHub provider:
export TF_VAR_github_oidc_provider_arn="arn:aws:iam::<account id>:oidc-provider/token.actions.githubusercontent.com"

terraform -chdir=infra/bootstrap init -backend=false -input=false
mv infra/bootstrap/backend.tf infra/bootstrap/backend.s3.tf.disabled
cp infra/bootstrap/local-backend.tf.example infra/bootstrap/backend.tf
terraform -chdir=infra/bootstrap init -reconfigure -input=false
terraform -chdir=infra/bootstrap plan -input=false -out=bootstrap.tfplan
terraform -chdir=infra/bootstrap show -no-color bootstrap.tfplan
terraform -chdir=infra/bootstrap apply -input=false bootstrap.tfplan

mv infra/bootstrap/backend.s3.tf.disabled infra/bootstrap/backend.tf
route_buddy_state_bucket="route-buddy-tfstate-${TF_VAR_aws_account_id}-${TF_VAR_aws_region}"
terraform -chdir=infra/bootstrap init -migrate-state \
  -backend-config="bucket=${route_buddy_state_bucket}" \
  -backend-config="region=${TF_VAR_aws_region}"
terraform -chdir=infra/bootstrap state list
```

The first `init -backend=false` validates provider installation without contacting S3. The
temporary local backend is required because the state bucket does not exist yet. If plan or apply
fails, restore `backend.s3.tf.disabled` to `backend.tf` before investigating; do not leave the
working tree on the local backend.

Verify the remote state and a bounded second plan before removing the local state copy:

```sh
aws s3api head-object \
  --bucket "$route_buddy_state_bucket" \
  --key bootstrap/terraform.tfstate
terraform -chdir=infra/bootstrap plan -detailed-exitcode -input=false
rm -f infra/bootstrap/terraform.tfstate infra/bootstrap/terraform.tfstate.backup
```

Exit code `0` from the second plan is the required no-change result. During any plan, native S3
locking creates `bootstrap/terraform.tfstate.tflock` and removes it on clean completion. Do not
continue if migration, remote-state verification, locking, or the no-change plan fails.

### Routine updates and verification

After the first bootstrap, every change runs by dispatching `Bootstrap AWS` from `main`. The
protected `aws-bootstrap` Environment approves the job before it requests an OIDC token. The job
applies only its displayed saved plan.

Verify trust without changing it:

```sh
aws iam get-role --role-name route-buddy-bootstrap \
  --query 'Role.AssumeRolePolicyDocument.Statement[0].Condition'
aws iam get-role --role-name route-buddy-aws-demo-deploy \
  --query 'Role.AssumeRolePolicyDocument.Statement[0].Condition'
```

Both policies must show audience `sts.amazonaws.com` and their exact GitHub Environment subject.
An attempted second push to an existing ECR tag must return `ImageTagAlreadyExistsException`.

### State recovery and break glass

The AWS account administrator owns break-glass recovery. Pause bootstrap and deployment
workflows, list versions of the affected state key, restore the selected prior S3 version as the
current object, then run a locked Terraform plan before resuming. Restoring creates another
version, so the displaced current state remains recoverable. Never automate force-unlock or
destroy.

Bootstrap resources are intentionally outside the application root. The demo deploy role cannot
read bootstrap or production state, change OIDC trust, modify its own role, remove runtime-role
permissions boundaries, or destroy the state bucket and ECR repositories.

## Known MVP limitations

1. Floci is a development emulator, not proof of real AWS durability, scaling, IAM, or service
   limits. The AWS root is mock-validated only; no live AWS plan or apply has been run.
2. Webhook auth is a shared secret, not signatures - prod item
3. Single region/market (SG), single user, English-first prompts
4. Generated exact schemas, OpenRouter's current Draft 7-based Auto Exacto routing, and one pinned
   correction reduce invalid proposals but cannot guarantee semantic intent. The `models` array
   falls back on request errors, not valid responses containing wrong proposals. Response Healing
   covers non-streaming `response_format` JSON content when enabled, not ordinary tool arguments.
   OpenRouter/provider routing can change over time; server validation and the confirmation gate
   guarantee safety.
5. Strict `provider.require_parameters` is not enabled. Both configured routes returned HTTP 404
   when it was combined with `parallel_tool_calls: false`; removing only that routing filter
   restored inference. Route Buddy still sends sequential-call requests, denies provider data
   collection, validates exact schemas server-side, rejects multiple calls, and gates writes.
6. The AWS demo intentionally has one task and one NAT gateway. WebSocket connections, session
   locks, and rate limits are in-process, and mock-Uber loses fares and trips when the task is
   replaced.
7. ECS assigns one task role to the whole task. Because API and mock-Uber share the required
   single task, both containers can obtain its DynamoDB credentials. Separate container IAM
   identities require separate tasks.

## Docs

- [Requirements](docs/high-level-requirements.md)
- [Approved design](docs/design.md)
- [Frozen contracts](docs/contracts.md)
- [Execution plan](docs/execution-plan.md)
- [Live RFC status](docs/rfc.md)
