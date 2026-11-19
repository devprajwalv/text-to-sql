from model.schema import analytics


def catalog():
    tables = []
    for table in analytics.tables.values():
        columns = []
        joins = []
        for col in table.columns:
            targets = [fk.target_fullname for fk in col.foreign_keys]
            description = col.doc or f"Links to {', '.join(targets)}."
            columns.append({"name": col.name, "type": str(col.type), "description": description})
            joins.extend(f"{table.name}.{col.name} = {target}" for target in targets)
        tables.append({"table_name": table.name, "description": table.comment, "columns": columns, "joins": joins})
    return tables


def document(table):
    lines = [table["table_name"], table["description"]]
    for col in table["columns"]:
        lines.append(f"{col['name']} ({col['type']}): {col['description']}")
    return "\n".join([*lines, *table["joins"]])
