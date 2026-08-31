# plano. V2

Reconstrução limpa do organizador acadêmico. A V2 usa Flask, SQLite, Jinja2 e JavaScript puro; possui um único banco em `instance/plano.db` e não lê nem migra o banco legado.

## Executar no Windows

```powershell
.\setup.ps1
.\run.ps1
```

 Abra `http://127.0.0.1:5051`. Essa porta é exclusiva da V2, evitando conflito com a aplicação legada.

Alternativa manual:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m database.migrations migrate
python app.py
```

## Verificação

```powershell
python -m unittest discover -s tests -v
```

O fluxo implementado preserva a separação entre Formação, Grade curricular e Estudos atuais. Sessões são a fonte de verdade do tempo; planejamento, recomendação e análises são derivados delas.
