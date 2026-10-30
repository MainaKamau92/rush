# DEMO-LOOKUP-01 — Trim customer display names

Team: Lantern Cart (fictional). Author: Nia Moss. Reviewer: Mira Vale.
Guideline: demo://lantern/guidelines/tenant-lookup/v1

Return the matching customer's display name without surrounding whitespace.
The caller supplies the tenant and external customer ID. External IDs can repeat
between tenants. Preserve tenant isolation and return None when no match exists.
An email address is not a display name. Do not change billing.
