"""Double-click to run ForgeLab Navigator without EDMC (needs Python 3.10+)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from forgelab_nav.standalone import main  # noqa: E402

main()
