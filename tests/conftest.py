import os
import subprocess
import time

import pytest

from dusty.config import Config

DAY = 86400
MB = 1024 * 1024


def make_file(path, size=1024, age_days=0, opened_days=None):
    """Create ``path`` with ``size`` bytes, modified ``age_days`` ago (and opened ``opened_days`` ago)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(os.urandom(min(size, 4096)) * (size // 4096) + os.urandom(size % 4096))
    now = time.time()
    mtime = now - age_days * DAY
    atime = now - (opened_days if opened_days is not None else age_days) * DAY
    os.utime(path, (atime, mtime))
    return path


def make_link(link, target):
    """Directory link: junction on Windows, symlink elsewhere. Skips the test if not possible."""
    if os.name == "nt":
        r = subprocess.run(["cmd", "/c", "mklink", "/J", link, target], capture_output=True)
        if r.returncode != 0:
            pytest.skip("cannot create junction")
    else:
        os.symlink(target, link, target_is_directory=True)


@pytest.fixture
def cfg():
    c = Config()
    c.workers = 4
    return c


@pytest.fixture
def mb():
    return MB
