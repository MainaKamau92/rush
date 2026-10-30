from customer_store import find_customer


def customer_name(connection, tenant_id, external_id):
    row = find_customer(connection, external_id, tenant_id)
    return row["email"] if row else None
