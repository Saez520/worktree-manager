import unittest

from worktree_manager.commit_message import (
    GENERIC_BODY,
    GENERIC_SUBJECT,
    compose_commit_message,
)


class CommitMessageTests(unittest.TestCase):
    def test_title_and_body_exact(self):
        subject, body = compose_commit_message(
            "feature", title="Cierre de prueba", body="Entrega: prueba. Motivo: verificacion."
        )
        self.assertEqual(subject, "Cierre de prueba [feature]")
        self.assertEqual(body, "Entrega: prueba. Motivo: verificacion.")

    def test_title_contains_work_id(self):
        subject, body = compose_commit_message(
            "feature", title="feature: cierre", body="cuerpo"
        )
        self.assertEqual(subject, "feature: cierre")
        self.assertEqual(body, "cuerpo")

    def test_empty_title_uses_fallback(self):
        subject, body = compose_commit_message("feature", title="   ", body="ignored")
        self.assertEqual(subject, "Complete feature (generic closure)")
        self.assertEqual(body, "No delivery description was available at closure time.")

    def test_title_without_id_appends_id(self):
        subject, body = compose_commit_message("CA-1", title="Entrega", body="")
        self.assertEqual(subject, "Entrega [CA-1]")
        self.assertEqual(body, "")

    def test_none_title_and_body(self):
        subject, body = compose_commit_message("x")
        self.assertEqual(subject, GENERIC_SUBJECT.format(work_id="x"))
        self.assertEqual(body, GENERIC_BODY)

    def test_crlf_title_normalized_to_single_line(self):
        subject, body = compose_commit_message(
            "feature", title="Linea1\r\nLinea2\0espacio  doble", body="a\r\nb"
        )
        self.assertEqual(subject, "Linea1 Linea2 espacio doble [feature]")
        self.assertEqual(body, "a\nb")

    def test_multiline_body_trims_trailing_spaces_and_blank_lines(self):
        subject, body = compose_commit_message(
            "feature", title="Titulo", body="linea  \n\nfinal  \n\n\n"
        )
        self.assertEqual(subject, "Titulo [feature]")
        self.assertEqual(body, "linea\n\nfinal")

    def test_empty_body_stays_empty_when_title_present(self):
        subject, body = compose_commit_message("feature", title="Titulo", body="   ")
        self.assertEqual(subject, "Titulo [feature]")
        self.assertEqual(body, "")

    def test_title_does_not_truncate(self):
        long_title = "T" * 500
        subject, _ = compose_commit_message("feature", title=long_title)
        self.assertEqual(subject, f"{long_title} [feature]")

    def test_body_preserves_internal_blank_lines(self):
        _, body = compose_commit_message("feature", title="Titulo", body="a\n\nb")
        self.assertEqual(body, "a\n\nb")


if __name__ == "__main__":
    unittest.main()
