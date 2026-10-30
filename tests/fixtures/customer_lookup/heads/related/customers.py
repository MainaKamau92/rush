from customer_store import lookup_for_export


def customer_name(connection, tenant_id, external_id):
    row = lookup_for_export(connection, external_id)
    return row["name"] if row else None
