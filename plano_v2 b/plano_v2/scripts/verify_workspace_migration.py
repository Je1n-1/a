"""Ensaia migration numa cópia temporária e verifica cada valor preexistente.

Sem argumentos: somente ensaio. --apply: aplica ao banco ativo depois do ensaio.
Não escreve dados de teste nem altera valores pessoais.
"""
import argparse
from contextlib import closing
import hashlib
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from database.connection import active_database_path, database_health
from database.migrations import migrate, migration_status


def snapshot(path, columns=None):
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as conn:
        if columns is None:
            names=[r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name<>'schema_migrations'")]
            columns={name:[r[1] for r in conn.execute(f'PRAGMA table_info("{name}")')] for name in names}
        values={}
        for name,fields in columns.items():
            select=','.join('"'+f+'"' for f in fields)
            rows=sorted(json.dumps(row,ensure_ascii=False,default=str) for row in conn.execute(f'SELECT {select} FROM "{name}"'))
            values[name]={'count':len(rows),'sha256':hashlib.sha256('\n'.join(rows).encode()).hexdigest()}
        return columns,values


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    path=active_database_path();columns,before=snapshot(path)
    with tempfile.TemporaryDirectory(prefix='plano-migration-check-') as folder:
        copy=Path(folder)/'test.db'
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as source,closing(sqlite3.connect(copy)) as target:
            source.backup(target)
        applied=migrate(copy)
        assert snapshot(copy,columns)[1]==before,'A migration alterou dados preexistentes no ensaio.'
        health=database_health(copy)
        assert health['integrity']=='ok' and not health['foreign_key_violations']
    if args.apply:
        migrate(path)
        assert snapshot(path,columns)[1]==before,'Valores existentes mudaram durante a aplicação.'
    print(json.dumps({'path':str(path),'trial_migrations':applied,'applied_to_active':args.apply,
        'preexisting_values_unchanged':True,'tables_verified':len(before),'tables':before,
        'health':database_health(path),'migration':migration_status(path)},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
