"""Handle Windows ANSI path comments written by the bundled Stan executable.

CmdStanPy 1.3 decodes CSV comments as UTF-8. Windows Stan may instead
write paths with the active ANSI code page. Only comment bytes are
normalized; parameter names, numerical draws and model equations are untouched.
"""
import sys


def normalize_comments(lines, encoding):
    for line in lines:
        try:
            line.decode('utf-8')
        except UnicodeDecodeError:
            line = line.decode(encoding, errors='strict').encode('utf-8')
        yield line


def configure_stan():
    if sys.platform != 'win32':
        return
    import ctypes
    from cmdstanpy.utils import stancsv
    original = stancsv.extract_key_val_pairs
    if getattr(original, '_morning_windows_comments', False):
        return
    encoding = 'cp' + str(ctypes.windll.kernel32.GetACP())

    def extract_key_val_pairs(comment_lines, remove_default_text=True):
        return original(normalize_comments(comment_lines, encoding), remove_default_text)

    extract_key_val_pairs._morning_windows_comments = True
    stancsv.extract_key_val_pairs = extract_key_val_pairs
