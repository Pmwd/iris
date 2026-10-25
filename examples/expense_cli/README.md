# expense_cli

A tiny stdlib-only expense tracker used as a safe acceptance workspace for Iris.

```powershell
python expense.py add 12.50 coffee --date 2026-10-20 --note beans
python expense.py list
python -m unittest discover -s tests
```

Data is stored in `expenses.json` by default. Keep the project dependency-free.
