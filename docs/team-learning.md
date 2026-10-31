# Team learning

rush learns only through an explicit, tested and approved team decision. An
ordinary comment, an accepted finding or a dismissal never changes future
reviews.

## Lifecycle

`proposed → evaluated → approved`. Each step is stored in SQLite
(migration 007): proposals, every revision, and the active learned rules.

1. **Propose.** Use either of these:
   - In a finding's review thread: `/rush learn <exact rule text> because <reason>`.
     This creates proposal `L…` with rule ID `learned.<fingerprint>`, scoped to
     the finding's file and repository, in the finding's category. The source
     discussion is the thread, and the owner is the requester.
   - Locally: `rush learning-propose proposal.json --proposer NAME`. The JSON
     needs `rule_id` (always `learned.…`, so it can never replace a file rule), `statement`, `rationale`, `category`, `owner`, `scope`
     (`path` plus optional `repository` and `symbol`), `source`, and `examples`
     (`violating` and `acceptable` fixture case IDs).

   A proposal is inactive. Its strict format has no permission fields, so it
   can't change tool or publication permissions.
2. **Inspect.** `rush learning-show L…` prints the exact proposal: its content
   hash, revision, examples and evaluation evidence. `rush learning-list`
   shows them all.
3. **Revise.** `rush learning-revise L… proposal.json` replaces the content,
   raises the revision, and clears the evaluation. The rule ID can't change,
   and an approved proposal can't be revised; propose a new rule instead.
4. **Evaluate.** `rush learning-evaluate L…` runs the active skill that applies
   team rules (`rule_ids` containing `*` or the rule ID). It reviews each
   example case from `tests/fixtures/customer_lookup` with the proposed rule
   applied, using the Meta model. Run it with the model override, for example
   `docker compose -f compose.yaml -f compose.model-access.yaml run --rm -T dev rush learning-evaluate L1`.
   - The skill's own acceptable examples always run as well, to catch false
     positives.
   - The rule's text is tested with a scope covering every file; its real
     scope applies once it is deployed.
   - A violating case passes when the review finds a problem under the
     proposed rule.
   - An acceptable case passes when it finds none.
   - An incomplete review fails the evaluation.

   The record keeps the rule version, the skill pin, the model settings and
   each case's result. Only a full pass moves the proposal to `evaluated`.
5. **Approve.** Use either of these:
   - In a thread: `/rush approve-learning L… <hash>`. The commenter must be in
     `RUSH_LEARNING_APPROVERS` (GitHub logins) and have current write access,
     and the proposal must be scoped to that same repository. Rules for other
     repositories, or for all of them, are approved locally.
   - Locally: `rush learning-approve L… --sha <hash> --approver NAME`. The
     approver must be in `RUSH_LEARNING_APPROVERS`; the local operator is the
     trust boundary.

   The hash, in full or at least its first 12 characters, must be the
   proposal's current version. An older or changed version is refused, and so
   is a version whose evaluation didn't pass. Repeating an approval changes
   nothing and creates no second rule. The approval records its channel
   (`github` or `cli`).

Every change replaces only the version that was read. If another change
happened meanwhile, it fails with "changed meanwhile" rather than undoing that
change. Rule IDs are unique, and every saved state is kept in an append-only
history.

## What approval changes

Approval records an active rule version (`learned.…`, version = revision)
with its approver and time. Later GitHub reviews add the approved learned rules
to the trusted rules file. They pass through the same scope, override,
conflict, drift and exception checks as every other rule, with no hidden
priority.
- A learned rule counts only while its approver is still in
  `RUSH_LEARNING_APPROVERS`.
- Learning approvers can't validate the operator's own rule files.
- A learned rule whose ID already appears in the rules file is skipped.

Local reviews use the explicit bundle from
`rush learning-export learned.json`: pass it as `--rules`, or merge it into
your rules file. Earlier review records are never changed; a re-review is a
new run.
