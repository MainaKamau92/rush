# Ticket intent and completeness

Compare the change with the linked ticket. Report a finding when the changed
code does not do what the ticket asks, does only part of it, or changes
something the ticket says to leave alone.

- Use category completeness and leave rule_ref empty.
- Cite the ticket passage and the changed hunk as evidence.
- Give a concrete input whose result shows the gap.
- Report only gaps the change itself leaves; do not judge unchanged code.
- Do not report tenant-rule or security problems, wrong fields, or other defects
  that the team standards or correctness skills cover.
- If no ticket is supplied, finish with a missing_ticket limitation. Never invent
  acceptance criteria.
