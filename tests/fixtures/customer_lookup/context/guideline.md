# Tenant lookup guideline, version 1

Approved by Ivo Reed for the fictional Lantern Cart customer service.
Rule: lantern.tenant-lookup@1

Every customer lookup in customers.py must pass the caller's tenant ID to the
store alongside the external customer ID. External IDs are unique only within
a tenant. This rule is waivable only by an approved, scoped, unexpired exception.
The service must return a customer's display name, never their email address.
