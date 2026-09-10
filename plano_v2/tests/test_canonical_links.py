import tempfile
import unittest
from pathlib import Path

from database.connection import connect
from database.migrations import migrate
from services import canonical_links


class CanonicalStudyLinkTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "canonical.db"
        migrate(self.database)
        with connect(self.database) as conn:
            self.f1 = conn.execute("INSERT INTO formacoes(name) VALUES ('Computação')").lastrowid
            self.f2 = conn.execute("INSERT INTO formacoes(name) VALUES ('Elétrica')").lastrowid
            self.d1 = conn.execute(
                "INSERT INTO disciplinas_grade(formation_id,name,code,workload_minutes,academic_status) VALUES (?,?,?,?,?)",
                (self.f1, "Cálculo I", "MAT101", 3600, "in_progress"),
            ).lastrowid
            self.d2 = conn.execute(
                "INSERT INTO disciplinas_grade(formation_id,name,code,workload_minutes,academic_status) VALUES (?,?,?,?,?)",
                (self.f2, "Cálculo I", "MAT101", 3600, "in_progress"),
            ).lastrowid
            self.s1 = conn.execute(
                "INSERT INTO materias_estudo(origin,curriculum_subject_id,status) VALUES ('curriculum',?,'active')",
                (self.d1,),
            ).lastrowid
            self.s2 = conn.execute(
                "INSERT INTO materias_estudo(origin,curriculum_subject_id,status) VALUES ('curriculum',?,'active')",
                (self.d2,),
            ).lastrowid

    def tearDown(self):
        self.temp.cleanup()

    def test_candidates_only_suggest_equivalence_and_never_link_automatically(self):
        with connect(self.database) as conn:
            candidates = canonical_links.equivalence_candidates(conn, self.d2)
            match = next(item for item in candidates["candidates"] if item["curriculum_subject_id"] == self.d1)
            self.assertGreaterEqual(match["score"], 100)
            self.assertFalse(candidates["automatic_linking"])
            self.assertIsNone(conn.execute("SELECT 1 FROM curriculum_study_links").fetchone())

    def test_explicit_merge_preserves_records_and_cancels_only_duplicate_automatic_plan(self):
        with connect(self.database) as conn:
            topic = conn.execute(
                "INSERT INTO topicos(study_subject_id,curriculum_subject_id,name,status) VALUES (?,?,?,'in_progress')",
                (self.s2, self.d2, "Limites"),
            ).lastrowid
            session = conn.execute(
                "INSERT INTO sessoes_estudo(study_subject_id,topic_id,date,duration_seconds,entry_method) VALUES (?,?,?,?,'manual')",
                (self.s2, topic, "2026-09-09", 1800),
            ).lastrowid
            canonical_plan = conn.execute(
                "INSERT INTO sessoes_planejadas(study_subject_id,scheduled_date,start_time,planned_duration_minutes,status,source) VALUES (?,?,?,?,?,'automatic')",
                (self.s1, "2026-09-10", "08:00", 50, "planned"),
            ).lastrowid
            duplicate_auto = conn.execute(
                "INSERT INTO sessoes_planejadas(study_subject_id,scheduled_date,start_time,planned_duration_minutes,status,source) VALUES (?,?,?,?,?,'automatic')",
                (self.s2, "2026-09-10", "08:00", 50, "planned"),
            ).lastrowid
            manual = conn.execute(
                "INSERT INTO sessoes_planejadas(study_subject_id,scheduled_date,start_time,planned_duration_minutes,status,source) VALUES (?,?,?,?,?,'manual')",
                (self.s2, "2026-09-11", "08:00", 50, "planned"),
            ).lastrowid
            result = canonical_links.link_curriculum_subject(
                conn, self.d2, self.s1, {"confirm": True, "merge_existing_study": True, "link_note": "mesma ementa"},
            )
            self.assertTrue(result["applied"])
            self.assertEqual(conn.execute("SELECT study_subject_id FROM sessoes_estudo WHERE id=?", (session,)).fetchone()[0], self.s1)
            self.assertEqual(conn.execute("SELECT study_subject_id FROM topicos WHERE id=?", (topic,)).fetchone()[0], self.s1)
            self.assertEqual(conn.execute("SELECT status FROM materias_estudo WHERE id=?", (self.s2,)).fetchone()[0], "archived")
            self.assertEqual(conn.execute("SELECT status FROM sessoes_planejadas WHERE id=?", (duplicate_auto,)).fetchone()[0], "cancelled")
            self.assertEqual(conn.execute("SELECT study_subject_id FROM sessoes_planejadas WHERE id=?", (manual,)).fetchone()[0], self.s1)
            self.assertEqual(conn.execute("SELECT status FROM sessoes_planejadas WHERE id=?", (canonical_plan,)).fetchone()[0], "planned")
            linked = canonical_links.linked_curriculum_subjects(conn, self.s1)
            self.assertEqual({item["id"] for item in linked}, {self.d1, self.d2})
            self.assertEqual(conn.execute("SELECT academic_status FROM disciplinas_grade WHERE id=?", (self.d2,)).fetchone()[0], "in_progress")

    def test_unlink_never_deletes_shared_data(self):
        with connect(self.database) as conn:
            canonical_links.link_curriculum_subject(
                conn, self.d2, self.s1, {"confirm": True, "merge_existing_study": True},
            )
            result = canonical_links.unlink_curriculum_subject(conn, self.d2, {"confirm": True})
            self.assertTrue(result["applied"])
            self.assertTrue(result["preserved_shared_data"])
            self.assertIsNone(conn.execute("SELECT 1 FROM curriculum_study_links WHERE curriculum_subject_id=?", (self.d2,)).fetchone())
            actions = [row[0] for row in conn.execute("SELECT action FROM curriculum_study_link_audit WHERE curriculum_subject_id=? ORDER BY id DESC", (self.d2,))]
            self.assertEqual(actions, ["unlinked", "merged_existing_study"])


if __name__ == "__main__":
    unittest.main()
