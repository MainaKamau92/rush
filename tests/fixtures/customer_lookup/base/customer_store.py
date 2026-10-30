def find_customer(connection, external_id, tenant_id=None):
    if tenant_id is None:
        return connection.execute(
            "SELECT * FROM customers WHERE external_id = ? ORDER BY tenant_id",
            (external_id,),
        ).fetchone()
    return connection.execute(
        "SELECT * FROM customers WHERE external_id = ? AND tenant_id = ?",
        (external_id, tenant_id),
    ).fetchone()


def lookup_for_export(connection, external_id):
    return find_customer(connection, external_id)
