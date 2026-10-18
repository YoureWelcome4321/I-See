#!/usr/bin/env python3
"""Создать или восстановить резервную копию SQLite базы."""
import argparse, sqlite3
from pathlib import Path
from server import DB_PATH

parser = argparse.ArgumentParser(); parser.add_argument("action", choices=("backup", "restore")); parser.add_argument("file", type=Path); args=parser.parse_args()
if args.action == "backup":
    source=sqlite3.connect(DB_PATH); target=sqlite3.connect(args.file); source.backup(target); target.close(); source.close(); print(f"Backup saved to {args.file}")
else:
    source=sqlite3.connect(args.file); target=sqlite3.connect(DB_PATH); source.backup(target); target.close(); source.close(); print(f"Database restored from {args.file}")
