import unittest
from stan_compat import normalize_comments, configure_stan


class WindowsCommentsTests(unittest.TestCase):
    def test_ansi_korean_path_and_numbers(self):
        line = '# file = C:/Users/남현승/Temp/result.csv\n'
        self.assertEqual(list(normalize_comments([line.encode('cp949'), b'# seed = 123\n'], 'cp949')),
                         [line.encode('utf-8'), b'# seed = 123\n'])

    def test_utf8_is_preserved(self):
        line = '# file = C:/한글/result.csv'.encode('utf-8')
        self.assertEqual(list(normalize_comments([line], 'cp949')), [line])

    def test_invalid_data_is_not_silently_replaced(self):
        with self.assertRaises(UnicodeDecodeError):
            list(normalize_comments([b'\xff'], 'ascii'))

    def test_idempotent(self):
        from cmdstanpy.utils import stancsv
        configure_stan()
        first = stancsv.extract_key_val_pairs
        configure_stan()
        self.assertIs(first, stancsv.extract_key_val_pairs)


if __name__ == '__main__':
    unittest.main()
