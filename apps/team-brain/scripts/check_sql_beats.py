"""The SQL-client beats of the video, run exactly as scripted against the dev schema.

Prints what each statement returns so the record kit can carry expected output.
"""

from __future__ import annotations

import oracledb

from team_brain.config import ORACLE_DSN, ORACLE_PASSWORD, ORACLE_USER

conn = oracledb.connect(user=ORACLE_USER, password=ORACLE_PASSWORD, dsn=ORACLE_DSN)
c = conn.cursor()
ctx = f"{ORACLE_USER}_CTX"

print("--- beat 9: fresh session as the schema owner, no identity ---")
c.execute("SELECT COUNT(*) FROM documents")
print("SELECT COUNT(*) FROM documents ->", c.fetchone()[0])
try:
    c.execute(f"BEGIN DBMS_SESSION.SET_CONTEXT('{ctx}','ALL_DOMAINS','Y'); END;")
    print("direct SET_CONTEXT -> allowed (BAD)")
except oracledb.DatabaseError as e:
    print("direct SET_CONTEXT ->", str(e).splitlines()[0])
c.execute("BEGIN tb_session.set_principal('jeff'); END;")
c.execute("SELECT COUNT(*) FROM documents")
print("after tb_session.set_principal('jeff') ->", c.fetchone()[0])
c.execute("SELECT title, JSON_SERIALIZE(domains) FROM documents ORDER BY 1")
for row in c.fetchall():
    print("   jeff sees:", row)
c.execute("BEGIN tb_session.set_principal('brian'); END;")
c.execute("SELECT COUNT(*) FROM documents")
print("after tb_session.set_principal('brian') ->", c.fetchone()[0])

print("--- beat 5 ---")
c.execute("SELECT VECTOR_DIMS(VECTOR_EMBEDDING(ALL_MINILM_L12_V2 USING 'hello' AS DATA)) FROM dual")
print("VECTOR_DIMS(...) ->", c.fetchone()[0])

print("--- beat 7: labels, INGEST mode ---")
c.execute("BEGIN tb_session.set_ingest; END;")
c.execute(
    "SELECT title, JSON_SERIALIZE(domains) FROM documents WHERE deleted_at IS NULL ORDER BY 1"
)
for row in c.fetchall():
    print("  ", row[0][:60], row[1])
conn.close()
