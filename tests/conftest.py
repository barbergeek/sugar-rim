# Share the holiday-menu fixtures (fake Bar Assistant, logged-in owner) across test files.
from tests.test_menu import ba, env, guest, owner  # noqa: F401
