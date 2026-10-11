from pathlib import Path
import sys
from audit_phase0 import make_app
from database import connection, migrations
if __name__ == '__main__':
    database=Path(sys.argv[1]).resolve()
    import os
    allowed=(Path(os.environ['LOCALAPPDATA'])/'Plano'/'v3-audit').resolve()
    if not database.is_relative_to(allowed): raise SystemExit('Only isolated audit databases are accepted.')
    connection.DATABASE_PATH=database
    migrations.migrate(database)
    make_app().run(host='127.0.0.1',port=5053,debug=False,use_reloader=False)
