# Correctness

Find behavior defects that the changed lines introduce: wrong values or fields,
broken conditions, lost data, crashes, and boundary mistakes that a concrete
input would trigger.

- Report only problems the change introduces or makes worse. Ignore unchanged
  code, even when it looks wrong.
- Leave rule_ref empty. Do not report a problem that an approved team rule in the
  policy source already covers; the team standards skill reports those. Leave
  such problems out without adding a limitation.
- Do not report partial delivery of the ticket unless the code returns plainly
  wrong data; the ticket intent skill reports incomplete work.
- Give a concrete triggering input and the wrong result it produces. Base it on
  values the code, ticket or supplied context shows are possible; do not propose
  a defect that depends on data the evidence cannot confirm, such as a stored
  field holding an unexpected type.
- Request a related snippet only when the defect cannot be judged from the
  change itself.
- Never claim that code or tests were run.
