# SPDX-License-Identifier: Apache-2.0
from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest

from scripts.update_readme_toc import END, START, main, table_of_contents, update_document


class ReadmeTocTests(unittest.TestCase):
    def test_unicode_punctuation_and_nested_headings(self):
        toc = table_of_contents('# Project\n## Установка\n### Ubuntu / Debian\n### Адресация: 0 или 1\n')
        self.assertEqual(toc, '- [Установка](#установка)\n  - [Ubuntu / Debian](#ubuntu--debian)\n  - [Адресация: 0 или 1](#адресация-0-или-1)')

    def test_fenced_code_comments_and_indentation_are_ignored(self):
        document = '## Visible\n```bash\n## Not a section\n```\n~~~~text\n### Not a section either\n~~~\n## Still code\n~~~~\n    ## Indented code\n<!--\n## Comment\n-->\n## End\n'
        self.assertEqual(table_of_contents(document), '- [Visible](#visible)\n- [End](#end)')

    def test_duplicate_slugs_and_formatted_titles(self):
        document = '# Same\n## Same\n## Same-1\n## **Same**\n## [Guide](guide.md) and `field_name`\n'
        toc = table_of_contents(document)
        self.assertIn('[Same](#same-1)', toc)
        self.assertIn('[Same-1](#same-1-1)', toc)
        self.assertIn('[Same](#same-2)', toc)
        self.assertIn('[Guide and field_name](#guide-and-field_name)', toc)

    def test_generated_block_is_idempotent_and_preserves_surrounding_text(self):
        prefix = '# Project\n\nIntro.\n'+START
        suffix = END+'\n\n## Оглавление\n\nBody.\n'
        updated = update_document(prefix+'\nobsolete\n'+suffix)
        self.assertTrue(updated.startswith(prefix))
        self.assertTrue(updated.endswith(suffix))
        self.assertNotIn('obsolete', updated)
        self.assertIn('[Оглавление](#оглавление-1)', updated)
        self.assertEqual(update_document(updated), updated)
        crlf = updated.replace('\n', '\r\n')
        self.assertEqual(update_document(crlf), crlf)

    def test_malformed_markers_are_rejected(self):
        for document in ('## No markers', END+'\n'+START, START+START+END):
            with self.assertRaises(ValueError):
                update_document(document)

    def test_check_does_not_write_and_generation_refreshes_changed_headings(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'Readme.md'
            original = START+'\n'+END+'\n## First\n'
            path.write_text(original, encoding='utf-8')
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(main([str(path), '--check']), 1)
                self.assertEqual(path.read_text(), original)
                self.assertEqual(main([str(path)]), 0)
                self.assertEqual(main([str(path), '--check']), 0)
                path.write_text(path.read_text()+'\n### Second\n')
                self.assertEqual(main([str(path), '--check']), 1)
                self.assertEqual(main([str(path)]), 0)
            self.assertIn('  - [Second](#second)', path.read_text())


if __name__ == '__main__':
    unittest.main()
