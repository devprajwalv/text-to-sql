"""Parse a small DML grammar and preview its effects using SELECT only."""
import json
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass

from lark import Lark, UnexpectedInput

from agent.hitl_guard import Blocked
from model.schema import analytics, products, sellers

MAX_ROWS = 10
TTL_SECONDS = 600
COLUMNS = {
    products.name: ("product_id", "category_name", "photos_qty"),
    sellers.name: ("seller_id", "city", "state", "zip_prefix"),
}

GRAMMAR = Lark(r"""
    ?start: (insert | update | delete) ";"?
    insert: "INSERT"i "INTO"i NAME "(" names ")" "VALUES"i values ("," values)*
    update: "UPDATE"i NAME "SET"i assignments "WHERE"i filters
    delete: "DELETE"i "FROM"i NAME "WHERE"i filters
    names: NAME ("," NAME)*
    values: "(" PARAM ("," PARAM)* ")"
    assignments: pair ("," pair)*
    filters: pair ("AND"i pair)*
    pair: NAME "=" PARAM
    NAME: /[a-zA-Z_][a-zA-Z_0-9]*/
    PARAM: /:[a-zA-Z_][a-zA-Z_0-9]*/
    %import common.WS
    %ignore WS
""", parser="lalr")

VERBS = {"add": "INSERT", "insert": "INSERT", "create": "INSERT", "change": "UPDATE",
         "set": "UPDATE", "update": "UPDATE", "edit": "UPDATE", "delete": "DELETE", "remove": "DELETE"}


def requested_change(question):
    # A separate UI/API intent opt-in AND an imperative directed at a business entity.
    # Arithmetic requests such as "add up the prices" stay outside this grammar.
    match = re.match(r"^(?:(?:can|could) you )?(?:please\s+)?(\w+)\s+"
                     r"(?:(?:the )?(?:category(?: name)?|photo count|city|state|zip prefix) (?:of|for) )?"
                     r"(?:(?:a|an|the|new|all|each|from|into)\s+)*"
                     r"(?:dim_)?(product|seller)s?\b", question.strip(), re.I)
    if not match or match[1].lower() not in VERBS:
        raise Blocked("Start the change with an action and target, for example: Change product p1's category to books.")
    return VERBS[match[1].lower()], f"dim_{match[2].lower()}s"


@dataclass
class Statement:
    operation: str
    table: str
    sql: str
    parameters: dict
    where: str
    values: list[dict]

    @property
    def key(self):
        return next(iter(analytics.tables[self.table].primary_key.columns)).name


def parse(sql, parameters, expected):
    if not isinstance(sql, str) or len(sql) > 12000 or not isinstance(parameters, dict):
        raise Blocked("A change requires one parameterized SQL statement and a parameter object.")
    try:
        tree = GRAMMAR.parse(sql)
    except UnexpectedInput:
        raise Blocked("Use one INSERT VALUES, UPDATE SET ... WHERE, or DELETE FROM ... WHERE statement. "
                      "Use named parameters and equality filters joined by AND.") from None
    operation = str(tree.data).upper()
    table = str(tree.children[0]).lower()
    if operation != expected or table not in COLUMNS:
        raise Blocked("The operation must match the request and target an editable business table.")
    used = set()

    def bind(column, token, filtering=False):
        name = str(token)[1:]
        if column not in COLUMNS[table] or name not in parameters:
            raise Blocked("Unknown column or missing bound value.")
        value = parameters[name]
        field = analytics.tables[table].c[column]
        if value is None:
            if filtering or not field.nullable:
                raise Blocked(f"{column} requires a value.")
        elif type(value) is not field.type.python_type:
            raise Blocked(f"Invalid value type for {column}.")
        elif isinstance(value, int) and abs(value) > 2**53 - 1:
            raise Blocked("Integer is too large to display exactly in the approval dialog.")
        elif isinstance(value, str) and len(value) > 2000:
            raise Blocked("Text values must be at most 2000 characters.")
        used.add(name)
        return value

    def bindings(pairs, filtering=False):
        values, clauses = {}, []
        for pair in pairs.children:
            col, param = pair.children
            col = str(col).lower()
            if col in values:
                raise Blocked("A column was specified twice.")
            values[col] = bind(col, param, filtering)
            clauses.append(f"{col} = {param}")
        return values, clauses

    rows = []
    where = ""
    if operation == "INSERT":
        columns = [str(x).lower() for x in tree.children[1].children]
        if len(columns) != len(set(columns)) or not set(columns) <= set(COLUMNS[table]):
            raise Blocked("Unknown or duplicate INSERT column.")
        key = next(iter(analytics.tables[table].primary_key.columns)).name
        if key not in columns or len(tree.children[2:]) > MAX_ROWS:
            raise Blocked(f"Supply a primary key for each insert and at most {MAX_ROWS} rows.")
        groups = []
        for group in tree.children[2:]:
            if len(group.children) != len(columns):
                raise Blocked("Each inserted row must match the column list.")
            rows.append({c: bind(c, p) for c, p in zip(columns, group.children)})
            groups.append("(" + ", ".join(group.children) + ")")
        canonical = f"INSERT INTO {table} ({', '.join(columns)}) VALUES {', '.join(groups)}"
    else:
        _, filters = bindings(tree.children[-1], filtering=True)
        where = " AND ".join(filters)
        if operation == "UPDATE":
            values, assignments = bindings(tree.children[1])
            if any(analytics.tables[table].c[c].primary_key for c in values):
                raise Blocked("Primary keys cannot be updated.")
            rows = [values]
            canonical = f"UPDATE {table} SET {', '.join(assignments)} WHERE {where}"
        else:
            canonical = f"DELETE FROM {table} WHERE {where}"
    if used != set(parameters):
        raise Blocked("Provide exactly the parameters used by the statement.")
    return Statement(operation, table, canonical, parameters, where, rows)


def parse_model_reply(raw, operation):
    try:
        obj = json.loads(raw)
    except ValueError:
        raise Blocked("The model could not produce a supported change proposal.") from None
    if not isinstance(obj, dict) or set(obj) != {"sql", "parameters"}:
        raise Blocked("The change proposal must contain SQL and bound parameters.")
    return parse(obj["sql"], obj["parameters"], operation)


def rows_by_key(conn, plan, keys):
    placeholders = ", ".join("?" for _ in keys)
    sql = f"SELECT * FROM main.{plan.table} WHERE {plan.key} IN ({placeholders}) ORDER BY {plan.key}"
    return [dict(row) for row in conn.execute(sql, keys)]


def preview(conn, plan):
    if plan.operation == "INSERT":
        keys = [r[plan.key] for r in plan.values]
        if len(set(keys)) != len(keys) or rows_by_key(conn, plan, keys):
            raise Blocked("One or more proposed primary keys already exist or are repeated.")
        after = [{col: r.get(col) for col in COLUMNS[plan.table]} for r in plan.values]
        return {"before": [], "after": sorted(after, key=lambda r: r[plan.key]), "affected_count": len(keys)}
    sql = f"SELECT * FROM main.{plan.table} WHERE {plan.where} ORDER BY {plan.key} LIMIT {MAX_ROWS + 1}"
    before = [dict(row) for row in conn.execute(sql, plan.parameters)]
    if not 1 <= len(before) <= MAX_ROWS:
        raise Blocked(f"A change must match between 1 and {MAX_ROWS} rows. Narrow or correct the filter.")
    after = [row | plan.values[0] for row in before] if plan.operation == "UPDATE" else []
    return {"before": before, "after": after, "affected_count": len(before)}


def preview_readonly(path, plan):
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        return preview(conn, plan)
