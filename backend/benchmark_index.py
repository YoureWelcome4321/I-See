#!/usr/bin/env python3
"""Как индекс ускоряет поиск товара по штрихкоду.

Скрипт создаёт отдельную временную базу по backend/schema.sql (рабочая база не трогается),
заливает в products N тестовых товаров и ищет M случайных штрихкодов дважды:
без индекса idx_products_barcode и с ним. Печатает время и план запроса SQLite.

    python3 backend/benchmark_index.py            # 20 000 товаров, 2 000 поисков
    python3 backend/benchmark_index.py --rows 100000 --lookups 5000
"""
import argparse
import random
import sqlite3
import tempfile
import time
from pathlib import Path

SCHEMA = Path(__file__).with_name("schema.sql")
QUERY = "SELECT id, name, price FROM products WHERE barcode = ?"
CATEGORIES = ("Молочные продукты", "Выпечка", "Сладости", "Крупы и макароны", "Напитки", "Мясо и рыба")


def fill(conn, rows):
    random.seed(42)
    barcodes = [f"460{random.randrange(10**9, 10**10)}" for _ in range(rows)]
    # One transaction for the whole batch: tens of thousands of inserts take a second, not minutes.
    with conn:
        conn.executemany(
            "INSERT INTO products(name, category, barcode, ingredients, allergens, price) VALUES (?, ?, ?, ?, ?, ?)",
            ((f"Тестовый товар №{i}", random.choice(CATEGORIES), code, "вода, сахар", "", random.randint(30, 900)) for i, code in enumerate(barcodes)),
        )
    return barcodes


def plan(conn):
    return " | ".join(row[-1] for row in conn.execute("EXPLAIN QUERY PLAN " + QUERY, ("0",)))


def measure(conn, targets):
    start = time.perf_counter()
    for code in targets:
        conn.execute(QUERY, (code,)).fetchone()
    return time.perf_counter() - start


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rows", type=int, default=20_000, help="сколько тестовых товаров залить (по умолчанию 20 000)")
    parser.add_argument("--lookups", type=int, default=2_000, help="сколько поисков по штрихкоду сделать (по умолчанию 2 000)")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as folder:
        conn = sqlite3.connect(Path(folder) / "benchmark.sqlite3")
        conn.executescript(SCHEMA.read_text(encoding="utf-8"))
        conn.execute("DROP INDEX idx_products_barcode")

        barcodes = fill(conn, args.rows)
        targets = random.sample(barcodes, min(args.lookups, len(barcodes)))
        print(f"Товаров в таблице: {conn.execute('SELECT COUNT(*) FROM products').fetchone()[0]:,}".replace(",", " "))
        print(f"Запрос: {QUERY}  ×{len(targets)}\n")

        before = measure(conn, targets)
        print("Без индекса")
        print(f"  план:  {plan(conn)}")
        print(f"  время: {before * 1000:.0f} мс  ({before / len(targets) * 1000:.3f} мс на поиск)\n")

        start = time.perf_counter()
        conn.execute("CREATE INDEX idx_products_barcode ON products(barcode)")
        built = time.perf_counter() - start

        after = measure(conn, targets)
        print(f"С индексом (создан за {built * 1000:.0f} мс)")
        print(f"  план:  {plan(conn)}")
        print(f"  время: {after * 1000:.0f} мс  ({after / len(targets) * 1000:.3f} мс на поиск)\n")
        print(f"Ускорение: ×{before / after:.0f}")
        conn.close()


if __name__ == "__main__":
    main()
