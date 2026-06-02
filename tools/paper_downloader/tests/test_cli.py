import sys, os
import importlib.util

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

spec = importlib.util.spec_from_file_location(
    "cli_module",
    os.path.join(os.path.dirname(__file__), '..', '__main__.py')
)
cli_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli_module)

def test_cli_importable():
    assert hasattr(cli_module, 'main')
    assert hasattr(cli_module, 'cmd_scan')
    assert hasattr(cli_module, 'cmd_stats')
