import re
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"


def test_every_endpoint_commits_before_the_response_is_sent():
    """With FastAPI's default dependency scope the commit runs after the response has gone out, so a client that reads
    straight after a write can get the old data (about one read in seven did). The test client is synchronous and cannot
    show that race, so this guards the cause: every use of the database dependency must say scope="function"."""
    bad = []
    for path in [*sorted((APP / "routers").glob("*.py")), APP / "deps.py"]:
        for n, line in enumerate(path.read_text(encoding="utf8").splitlines(), 1):
            if re.search(r"Depends\(\s*db_dep\s*\)", line):
                bad.append(f"{path.name}:{n}")
    assert bad == [], f'use Depends(db_dep, scope="function") at: {bad}'
