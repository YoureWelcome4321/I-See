"""Database requirements: catalog in SQLite, JOIN in the API, transaction rollback, persistence, backup."""
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend import server


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.db_path = Path(folder.name) / "test.sqlite3"
        for target, value in ((server, "DB_PATH"), (server, "UPLOADS")):
            patcher = patch.object(target, value, self.db_path if value == "DB_PATH" else Path(folder.name))
            patcher.start()
            self.addCleanup(patcher.stop)
        env = patch.dict(os.environ, {"ADMIN_PASSWORD": "test-admin-pw"})
        env.start()
        self.addCleanup(env.stop)
        server.init_db()
        self.client = TestClient(server.app)

    def sign_up(self, restrictions):
        response = self.client.post("/api/register", json={"name": "Анна", "phone": "+79001234567", "password": "test-pass-123", "restrictions": restrictions})
        return {"Authorization": f"Bearer {response.json()['token']}"}

    def admin(self):
        token = self.client.post("/api/login", json={"login": "admin", "password": "test-admin-pw"}).json()["token"]
        return {"Authorization": f"Bearer {token}"}

    def count(self, table):
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def test_catalog_is_seeded_into_the_database(self):
        products = self.client.get("/api/products").json()
        self.assertEqual(len(products), len(server.CATALOG_SEED))
        self.assertIn("Кефир 1%", {p["name"] for p in products})

    def test_deleted_seed_product_does_not_come_back_after_restart(self):
        kefir = next(p for p in self.client.get("/api/products").json() if p["name"] == "Кефир 1%")
        self.client.delete(f"/api/products/{kefir['id']}", headers=self.admin())
        server.init_db()  # a server restart
        self.assertNotIn("Кефир 1%", {p["name"] for p in self.client.get("/api/products").json()})

    def test_checks_take_the_product_name_from_the_join(self):
        headers = self.sign_up([{"name": "молоко", "type": "allergy"}])
        self.client.post("/api/checks", json={"product_id": 1}, headers=headers)
        product = self.client.get("/api/products/1").json()
        self.client.put("/api/products/1", json={**product, "name": "Йогурт клубничный 2,5%"}, headers=self.admin())
        check = self.client.get("/api/checks", headers=headers).json()[0]
        self.assertEqual(check["product_name"], "Йогурт клубничный 2,5%")
        self.assertEqual(check["product_category"], "Молочные продукты")

    def test_failed_second_step_rolls_back_the_check(self):
        # "молоко" as both an allergy and "не ем" gives two equal matches: the second
        # INSERT into check_matches breaks its primary key, so the whole check must roll back.
        headers = self.sign_up([{"name": "молоко", "type": "allergy"}, {"name": "молоко", "type": "avoid"}])
        response = self.client.post("/api/checks", json={"product_id": 1}, headers=headers)
        self.assertEqual(response.status_code, 500)
        self.assertEqual((self.count("checks"), self.count("check_matches")), (0, 0))

    def test_successful_check_commits_both_tables(self):
        headers = self.sign_up([{"name": "молоко", "type": "allergy"}])
        self.assertEqual(self.client.post("/api/checks", json={"product_id": 1}, headers=headers).status_code, 201)
        self.assertEqual((self.count("checks"), self.count("check_matches")), (1, 1))

    def test_data_survives_a_restart(self):
        headers = self.sign_up([])
        self.client.post("/api/checks", json={"product_id": 2}, headers=headers)
        server.init_db()
        fresh = TestClient(server.app)
        self.assertEqual(len(fresh.get("/api/checks", headers=headers).json()), 1)

    def test_backup_restores_deleted_rows(self):
        backup = self.db_path.with_name("backup.sqlite3")
        with sqlite3.connect(self.db_path) as source, sqlite3.connect(backup) as target:
            source.backup(target)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM products WHERE id IN (1, 2)")
        self.assertEqual(self.count("products"), len(server.CATALOG_SEED) - 2)
        with sqlite3.connect(backup) as source, sqlite3.connect(self.db_path) as target:
            source.backup(target)
        self.assertEqual(self.count("products"), len(server.CATALOG_SEED))


if __name__ == "__main__":
    unittest.main()
