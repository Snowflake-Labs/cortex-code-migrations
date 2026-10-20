#!/usr/bin/env python3
"""Install unixODBC and Microsoft ODBC Driver 18 for SQL Server without root (Linux).

For a local Data Exchange Worker on a machine where the user has no sudo. The
packages are fetched as the user (``apt-get download`` / ``dnf download`` for
unixODBC, packages.microsoft.com for msodbcsql18), unpacked under a prefix in
the home directory, and wired up with a private ``odbcinst.ini``:

    <prefix>/usr/...                        unixODBC (only what the system lacks)
    <prefix>/opt/microsoft/msodbcsql18/...  the driver
    <prefix>/etc/odbcinst.ini               registers "ODBC Driver 18 for SQL Server"

The worker does not read a shell profile, but ``scai`` loads the project's
``.env`` and the worker inherits it, so ``ODBCSYSINI`` and ``LD_LIBRARY_PATH``
go there (``--project-dir``). ``odbcinst``/``isql`` wrappers that set the same
variables go in ``~/.local/bin``. ``--check`` verifies an existing install for
``--project-dir``, or else that the system has the driver.

Microsoft's licence must be accepted first: ``--accept-eula``
(https://aka.ms/odbc18eula). Supported: Debian 11-13, Ubuntu 20.04-24.04, and
RHEL 8/9 and its rebuilds (Rocky, AlmaLinux, Oracle Linux, CentOS Stream).
Stdlib only, Python 3.8+.

Remove it with ``rm -rf <prefix>``, the two wrappers, and the two ``.env`` lines.
"""

from __future__ import annotations

import argparse
import bz2
import gzip
import hashlib
import io
import lzma
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # annotations only: the script runs on Python 3.8
    from collections.abc import Callable, Iterable, Mapping, Sequence

    Runner = Callable[..., subprocess.CompletedProcess[str]]

EULA_URL = "https://aka.ms/odbc18eula"
DRIVER_NAME = "ODBC Driver 18 for SQL Server"
DRIVER_PACKAGE = "msodbcsql18"
MS_BASE = "https://packages.microsoft.com"
DEFAULT_PREFIX = Path.home() / ".local" / "share" / "scai" / "odbc"
DEFAULT_BIN_DIR = Path.home() / ".local" / "bin"
PREFIX_MARKER = ".install_odbc_user"
WRAPPER_MARKER = "# Written by install_odbc_user.py"
ENV_COMMENT = "# User-level unixODBC + msodbcsql18 (install_odbc_user.py)"
WRAPPED_TOOLS = ("odbcinst", "isql")
OTHER_ROUTES = "Other routes: a sudo install you run yourself, or a worker on SPCS."

_UBUNTU_CODENAMES = {"focal": "20.04", "jammy": "22.04", "noble": "24.04"}
_RHEL_IDS = {"rhel", "centos", "rocky", "almalinux", "ol"}
_DEB_ARCH = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}
_RPM_ARCH = {
    "x86_64": "x86_64",
    "amd64": "x86_64",
    "aarch64": "aarch64",
    "arm64": "aarch64",
}
_APT_BASE = ("unixodbc", "odbcinst")
# The driver links libgssapi_krb5.so.2 without its package declaring it.
_APT_ALWAYS = ("libgssapi-krb5-2",)
# A second libc or libstdc++ on LD_LIBRARY_PATH would break every process the worker starts.
_NEVER_UNPACK = re.compile(
    r"^(libc6|libc-bin|libgcc-s1|libgcc1|libstdc\+\+6|glibc|libgcc|libstdc\+\+|debconf)$"
)
_DIGESTS = {"sha256": "sha256", "sha384": "sha384", "sha512": "sha512"}


class InstallError(Exception):
    """A step failed; the message says what to do."""


@dataclass(frozen=True)
class Target:
    """Where msodbcsql18 comes from for this distribution."""

    family: str  # "deb" or "rpm"
    repo_url: str
    codename: str | None = None


def parse_os_release(text: str) -> dict[str, str]:
    """Parse /etc/os-release into a dict, unquoting values."""
    fields: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        fields[key.strip()] = _unquote(value.strip())
    return fields


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def resolve_target(
    fields: Mapping[str, str], repo_override: str | None = None
) -> Target:
    """Map os-release fields to Microsoft's package repository for this distribution."""
    os_id = fields.get("ID", "").lower()
    like = fields.get("ID_LIKE", "").lower().split()
    version = fields.get("VERSION_ID", "")

    if os_id == "ubuntu" or "ubuntu" in like:
        codename = fields.get("UBUNTU_CODENAME") or fields.get("VERSION_CODENAME", "")
        ubuntu_version = (
            version if os_id == "ubuntu" else _UBUNTU_CODENAMES.get(codename, "")
        )
        if repo_override and codename:
            return Target("deb", repo_override.rstrip("/"), codename)
        if not codename or not ubuntu_version:
            raise InstallError(_unsupported(fields))
        return Target("deb", f"{MS_BASE}/ubuntu/{ubuntu_version}/prod", codename)

    if os_id == "debian" or "debian" in like:
        codename = fields.get("VERSION_CODENAME", "")
        major = version.split(".")[0]
        if repo_override and codename:
            return Target("deb", repo_override.rstrip("/"), codename)
        if os_id != "debian" or not codename or not major:
            raise InstallError(_unsupported(fields))
        return Target("deb", f"{MS_BASE}/debian/{major}/prod", codename)

    # Amazon Linux says ID_LIKE="centos rhel fedora" but has no rhel/<VERSION_ID> repository.
    if os_id != "amzn" and (os_id in _RHEL_IDS or "rhel" in like):
        major = version.split(".")[0]
        if repo_override:
            return Target("rpm", repo_override.rstrip("/"))
        if not major:
            raise InstallError(_unsupported(fields))
        return Target("rpm", f"{MS_BASE}/rhel/{major}/prod")

    raise InstallError(_unsupported(fields))


def _unsupported(fields: Mapping[str, str]) -> str:
    name = fields.get("PRETTY_NAME") or fields.get("ID") or "this Linux distribution"
    return f"No user-level install for {name}: it covers Debian, Ubuntu and RHEL-family systems."


def machine_arch(family: str, machine: str | None = None) -> str:
    """The package architecture name for this machine."""
    machine = (machine or platform.machine()).lower()
    table = _DEB_ARCH if family == "deb" else _RPM_ARCH
    if machine not in table:
        raise InstallError(
            f"msodbcsql18 has no package for the {machine} architecture."
        )
    return table[machine]


def version_key(version: str) -> tuple[int, ...]:
    """Order package versions by their numeric parts (epoch first)."""
    epoch, _, rest = version.rpartition(":")
    return (int(epoch) if epoch.isdigit() else 0,) + tuple(
        int(n) for n in re.findall(r"\d+", rest)
    )


def parse_deb_packages(text: str) -> list[dict[str, str]]:
    """Parse a Debian ``Packages`` index into one dict per stanza."""
    stanzas: list[dict[str, str]] = []
    current: dict[str, str] = {}
    last_key = ""
    for line in text.splitlines():
        if not line.strip():
            if current:
                stanzas.append(current)
            current, last_key = {}, ""
        elif line[0] in " \t" and last_key:
            current[last_key] += "\n" + line.strip()
        elif ":" in line:
            last_key, value = line.split(":", 1)
            current[last_key] = value.strip()
    if current:
        stanzas.append(current)
    return stanzas


def pick_deb(
    stanzas: Iterable[Mapping[str, str]], name: str, arch: str
) -> Mapping[str, str]:
    """The newest stanza for ``name`` built for ``arch``."""
    matches = [
        s
        for s in stanzas
        if s.get("Package") == name and s.get("Architecture") in (arch, "all")
    ]
    if not matches:
        raise InstallError(f"{name} is not in Microsoft's repository for {arch}.")
    return max(matches, key=lambda s: version_key(s.get("Version", "")))


def deb_depends(stanza: Mapping[str, str]) -> list[list[str]]:
    """Each dependency of a stanza as its alternatives' package names, versions dropped."""
    groups: list[list[str]] = []
    for group in stanza.get("Depends", "").split(","):
        names = [
            re.split(r"[\s(:]", alt.strip(), maxsplit=1)[0] for alt in group.split("|")
        ]
        names = [n for n in names if n]
        if names:
            groups.append(names)
    return groups


_RPM_COMMON = "{http://linux.duke.edu/metadata/common}"
_RPM_REPO = "{http://linux.duke.edu/metadata/repo}"


def primary_href(repomd: bytes) -> str:
    """The location of ``primary.xml`` in a ``repomd.xml``."""
    root = ET.fromstring(repomd)
    for data in root.iter(f"{_RPM_REPO}data"):
        if data.get("type") == "primary":
            location = data.find(f"{_RPM_REPO}location")
            if location is not None and location.get("href"):
                return str(location.get("href"))
    raise InstallError("Microsoft's RPM repository has no primary index.")


def pick_rpm(primary: bytes, name: str, arch: str) -> dict[str, str]:
    """``{"href", "algo", "digest", "version"}`` of the newest ``name`` for ``arch``."""
    best: dict[str, str] | None = None
    best_key: tuple[int, ...] = ()
    for pkg in ET.fromstring(primary).iter(f"{_RPM_COMMON}package"):
        if pkg.findtext(f"{_RPM_COMMON}name") != name:
            continue
        if pkg.findtext(f"{_RPM_COMMON}arch") not in (arch, "noarch"):
            continue
        ver = pkg.find(f"{_RPM_COMMON}version")
        loc = pkg.find(f"{_RPM_COMMON}location")
        checksum = pkg.find(f"{_RPM_COMMON}checksum")
        if ver is None or loc is None:
            continue
        version = f"{ver.get('epoch', '0')}:{ver.get('ver', '')}-{ver.get('rel', '')}"
        key = version_key(version)
        if best is None or key > best_key:
            best_key = key
            best = {
                "href": str(loc.get("href")),
                "algo": checksum.get("type", "") if checksum is not None else "",
                "digest": (checksum.text or "").strip() if checksum is not None else "",
                "version": version,
            }
    if best is None:
        raise InstallError(f"{name} is not in Microsoft's repository for {arch}.")
    return best


def decompress(name: str, data: bytes) -> bytes:
    """Undo the compression named by ``name``'s suffix."""
    if name.endswith(".gz"):
        return gzip.decompress(data)
    if name.endswith(".xz"):
        return lzma.decompress(data)
    if name.endswith(".bz2"):
        return bz2.decompress(data)
    if name.endswith(".zst"):
        if not shutil.which("zstd"):
            raise InstallError(
                f"{name} is zstd-compressed and `zstd` is not installed."
            )
        return subprocess.run(
            ["zstd", "-dc"], input=data, stdout=subprocess.PIPE, check=True
        ).stdout
    return data


def _safe_members(tar: tarfile.TarFile, dest: Path) -> list[tarfile.TarInfo]:
    """Regular files, dirs and in-tree links only; nothing that lands outside ``dest``."""
    root = dest.resolve()
    members: list[tarfile.TarInfo] = []
    for member in tar.getmembers():
        member.name = member.name.lstrip("/")
        while member.name.startswith("./"):
            member.name = member.name[2:]
        if not member.name or member.name == ".":
            continue
        target = (root / member.name).resolve()
        if root != target and root not in target.parents:
            continue
        if member.issym() or member.islnk():
            if os.path.isabs(member.linkname):
                continue
            base = target.parent if member.issym() else root
            link = (base / member.linkname).resolve()
            if root != link and root not in link.parents:
                continue
        elif not (member.isfile() or member.isdir()):
            continue
        members.append(member)
    return members


def _extract_tar_bytes(name: str, data: bytes, dest: Path) -> None:
    with tarfile.open(fileobj=io.BytesIO(decompress(name, data)), mode="r:") as tar:
        members = _safe_members(tar, dest)
        if hasattr(tarfile, "tar_filter"):
            tar.extractall(dest, members=members, filter="tar")
        else:
            tar.extractall(dest, members=members)


def read_ar(data: bytes) -> dict[str, bytes]:
    """The members of a ``.deb`` (an ``ar`` archive), by name."""
    if not data.startswith(b"!<arch>\n"):
        raise InstallError("Not a .deb archive.")
    members: dict[str, bytes] = {}
    offset = 8
    while offset + 60 <= len(data):
        header = data[offset : offset + 60]
        name = header[:16].decode("ascii").strip().rstrip("/")
        size = int(header[48:58].decode("ascii").strip())
        start = offset + 60
        members[name] = data[start : start + size]
        offset = start + size + (size % 2)
    return members


def extract_deb(deb: Path, dest: Path, run: Runner = subprocess.run) -> None:
    """Unpack a ``.deb``'s files under ``dest`` (``dpkg-deb -x`` when present)."""
    if shutil.which("dpkg-deb"):
        run(["dpkg-deb", "-x", str(deb), str(dest)], check=True)
        return
    members = read_ar(deb.read_bytes())
    data_name = next((n for n in members if n.startswith("data.tar")), None)
    if data_name is None:
        raise InstallError(f"{deb.name} has no data archive.")
    _extract_tar_bytes(data_name, members[data_name], dest)


def extract_rpm(rpm: Path, dest: Path, run: Runner = subprocess.run) -> None:
    """Unpack an ``.rpm``'s files under ``dest`` (``rpm2cpio | cpio``, else ``rpm2archive``)."""
    if shutil.which("rpm2cpio") and shutil.which("cpio"):
        cpio = run(["rpm2cpio", str(rpm)], stdout=subprocess.PIPE, check=True).stdout
        run(
            ["cpio", "-idmu", "--quiet", "--no-absolute-filenames"],
            input=cpio,
            cwd=str(dest),
            check=True,
        )
        return
    if shutil.which("rpm2archive"):
        with rpm.open("rb") as payload:
            tgz = run(
                ["rpm2archive", "-"], stdin=payload, stdout=subprocess.PIPE, check=True
            ).stdout
        _extract_tar_bytes("payload.tar.gz", tgz, dest)
        return
    raise InstallError(
        "Unpacking an .rpm needs `rpm2cpio` and `cpio`, or `rpm2archive`."
    )


def http_get(url: str) -> bytes:
    """GET ``url`` (honours https_proxy)."""
    request = urllib.request.Request(
        url, headers={"User-Agent": "scai-install-odbc-user"}
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.read()
    except OSError as exc:
        raise InstallError(f"Could not download {url}: {exc}") from exc


def _write_checked(data: bytes, algo: str, digest: str, path: Path) -> Path:
    if algo not in _DIGESTS or not digest:
        raise InstallError(
            f"{path.name} has no usable checksum in Microsoft's index; not installing it."
        )
    if hashlib.new(_DIGESTS[algo], data).hexdigest() != digest.lower():
        raise InstallError(
            f"{path.name} failed its {algo.upper()} check; not installing it."
        )
    path.write_bytes(data)
    return path


def fetch_driver_deb(
    target: Target, arch: str, workdir: Path, get: Callable[[str], bytes] = http_get
) -> tuple[Path, list[list[str]]]:
    """Download msodbcsql18's ``.deb``; return it and its dependencies."""
    index_url = (
        f"{target.repo_url}/dists/{target.codename}/main/binary-{arch}/Packages.gz"
    )
    index = gzip.decompress(get(index_url)).decode("utf-8", "replace")
    stanza = pick_deb(parse_deb_packages(index), DRIVER_PACKAGE, arch)
    filename = stanza["Filename"]
    data = get(f"{target.repo_url}/{filename}")
    return _write_checked(
        data, "sha256", stanza.get("SHA256", ""), workdir / Path(filename).name
    ), deb_depends(stanza)


def fetch_driver_rpm(
    target: Target, arch: str, workdir: Path, get: Callable[[str], bytes] = http_get
) -> Path:
    """Download msodbcsql18's ``.rpm``."""
    href = primary_href(get(f"{target.repo_url}/repodata/repomd.xml"))
    pkg = pick_rpm(
        decompress(href, get(f"{target.repo_url}/{href}")), DRIVER_PACKAGE, arch
    )
    data = get(f"{target.repo_url}/{pkg['href']}")
    return _write_checked(
        data, pkg["algo"], pkg["digest"], workdir / Path(pkg["href"]).name
    )


def apt_missing(simulation: str) -> list[str]:
    """Packages an ``apt-get -s install`` would newly install (upgrades and core runtime excluded)."""
    names = []
    for line in simulation.splitlines():
        match = re.match(r"^Inst (\S+)(.*)$", line)
        if not match or match.group(2).lstrip().startswith("["):
            continue  # "Inst pkg [old] (new …)" is an upgrade of an installed package
        name = match.group(1).split(":")[0]
        if not _NEVER_UNPACK.match(name):
            names.append(name)
    return names


class _AptFailure(Exception):
    pass


def _apt(
    run: Runner, opts: Sequence[str], *args: str, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    return run(
        ["apt-get", *opts, *args],
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
    )


def _tail(proc: subprocess.CompletedProcess[str]) -> str:
    return (proc.stderr or proc.stdout or "").strip()[-400:]


def _apt_resolve(
    run: Runner, opts: Sequence[str], extras: Sequence[list[str]]
) -> list[str]:
    """What apt would newly install for unixODBC plus each installable extra dependency."""
    simulate = ("-s", "-q", "install", "--no-install-recommends")
    base = _apt(run, opts, *simulate, *_APT_BASE)
    if base.returncode != 0:
        raise _AptFailure(_tail(base))
    missing = apt_missing(base.stdout)
    for alternatives in extras:
        for name in alternatives:
            sim = _apt(run, opts, *simulate, *_APT_BASE, name)
            if sim.returncode == 0:
                missing += [m for m in apt_missing(sim.stdout) if m not in missing]
                break
    return missing


def _private_apt_lists(workdir: Path) -> list[str]:
    lists, cache = workdir / "apt-lists", workdir / "apt-cache"
    (lists / "partial").mkdir(parents=True)
    (cache / "archives" / "partial").mkdir(parents=True)
    return [
        "-o",
        f"Dir::State::Lists={lists}",
        "-o",
        f"Dir::Cache={cache}",
        "-o",
        "Debug::NoLocking=1",
    ]


def fetch_unixodbc_deb(
    depends: Sequence[list[str]], workdir: Path, run: Runner = subprocess.run
) -> list[Path]:
    """Download (as the user) the unixODBC packages, and driver dependencies, the system lacks.

    The system's package lists can be stale or empty and only root may refresh
    them, so a failure is retried once against lists refreshed into ``workdir``.
    """
    extras = [
        g
        for g in depends
        if not set(g) & set(_APT_BASE) and not any(_NEVER_UNPACK.match(n) for n in g)
    ]
    extras += [[name] for name in _APT_ALWAYS if not any(name in g for g in extras)]
    downloads = workdir / "debs"
    downloads.mkdir()
    error = ""
    for private in (False, True):
        opts: list[str] = []
        if private:
            opts = _private_apt_lists(workdir)
            refreshed = _apt(run, opts, "-q", "update")
            if refreshed.returncode != 0:
                error = _tail(refreshed)
                break
        try:
            missing = _apt_resolve(run, opts, extras)
        except _AptFailure as exc:
            error = str(exc)
            continue
        if not missing:
            return []
        got = _apt(run, opts, "download", *missing, cwd=downloads)
        if got.returncode == 0:
            return sorted(downloads.glob("*.deb"))
        error = _tail(got)
    raise InstallError(
        f"apt could not fetch unixODBC: {error}. Its package lists may be out of date; "
        "ask an administrator to run `sudo apt-get update`."
    )


def fetch_unixodbc_rpm(workdir: Path, run: Runner = subprocess.run) -> list[Path]:
    """Download (as the user) unixODBC and the dependencies the system lacks."""
    if run(["rpm", "-q", "unixODBC"], capture_output=True, text=True).returncode == 0:
        return []
    dest = workdir / "unixodbc"
    dest.mkdir()
    if shutil.which("dnf"):
        cmd = ["dnf", "download", "-q", "--resolve", "--destdir", str(dest), "unixODBC"]
    elif shutil.which("yumdownloader"):
        cmd = ["yumdownloader", "-q", "--resolve", "--destdir", str(dest), "unixODBC"]
    else:
        raise InstallError(
            "Neither `dnf download` nor `yumdownloader` is available to fetch unixODBC."
        )
    got = run(cmd, capture_output=True, text=True)
    if got.returncode != 0:
        raise InstallError(
            f"Downloading unixODBC failed: {_tail(got)}. On subscribed RHEL a non-root user may "
            "not be able to read the repositories; ask an administrator."
        )
    return sorted(
        p
        for p in dest.glob("*.rpm")
        if not _NEVER_UNPACK.match(re.sub(r"-\d.*$", "", p.name))
    )


def find_driver(prefix: Path) -> Path:
    """The msodbcsql18 shared library under ``prefix``."""
    lib64 = prefix / "opt" / "microsoft" / "msodbcsql18" / "lib64"
    libs = sorted(
        (p for p in lib64.glob("libmsodbcsql-18*.so*") if not p.is_symlink()),
        key=lambda p: version_key(p.name),
    )
    if not libs:
        raise InstallError(f"{DRIVER_NAME} is not installed under {prefix}.")
    return libs[-1]


def library_dirs(prefix: Path) -> list[Path]:
    """Directories under ``prefix`` holding the unpacked unixODBC (and dependency) libraries."""
    dirs = set()
    for top in ("usr/lib", "usr/lib64", "lib", "lib64"):
        base = prefix / top
        if base.is_dir():
            dirs.update(
                p.parent for p in base.rglob("*.so*") if p.is_file() or p.is_symlink()
            )
    return sorted(dirs)


def odbcinst_ini(driver: Path) -> str:
    """An ``odbcinst.ini`` registering the driver."""
    return f"[{DRIVER_NAME}]\nDescription=Microsoft {DRIVER_NAME}\nDriver={driver}\nUsageCount=1\n"


def env_values(prefix: Path, lib_dirs: Sequence[Path]) -> dict[str, str]:
    """The variables a process needs to find this install."""
    values = {"ODBCSYSINI": str(prefix / "etc")}
    if lib_dirs:
        values["LD_LIBRARY_PATH"] = ":".join(str(d) for d in lib_dirs)
    return values


def format_env_value(value: str) -> str:
    """A ``.env`` value: bare when it is plain path characters, else single-quoted (literal)."""
    if re.fullmatch(r"[A-Za-z0-9_./:@%+,=-]+", value):
        return value
    if "'" in value:
        raise InstallError(
            f"Cannot write {value!r} to .env: it contains a single quote. Pass --prefix."
        )
    return f"'{value}'"


_ENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")


def read_env(text: str) -> dict[str, str]:
    """The last value of each key in a ``.env``."""
    values = {}
    for line in text.splitlines():
        match = _ENV_LINE.match(line)
        if match:
            values[match.group(1)] = _unquote(match.group(2).strip())
    return values


def merge_env_values(
    values: Mapping[str, str], existing: Mapping[str, str], prefix: Path
) -> dict[str, str]:
    """``values`` with ``LD_LIBRARY_PATH`` keeping the entries already there that are not this install's.

    An empty ``LD_LIBRARY_PATH`` in the result means the key is to be removed.
    """
    merged = dict(values)
    ours = [p for p in values.get("LD_LIBRARY_PATH", "").split(":") if p]
    theirs = [
        p
        for p in existing.get("LD_LIBRARY_PATH", "").split(":")
        if p and p not in ours and Path(p) != prefix and prefix not in Path(p).parents
    ]
    if ours or "LD_LIBRARY_PATH" in existing:
        merged["LD_LIBRARY_PATH"] = ":".join(ours + theirs)
    return merged


def upsert_env(text: str, values: Mapping[str, str]) -> str:
    """``text`` with each of ``values`` set once: replaced where present, appended otherwise.

    A key whose value is empty is removed.
    """
    pending = {k: v for k, v in values.items() if v}
    seen = set()
    out: list[str] = []
    for line in text.splitlines():
        match = _ENV_LINE.match(line)
        key = match.group(1) if match else None
        if key in values:
            if key not in seen and values[key]:
                out.append(f"{key}={format_env_value(values[key])}")
                pending.pop(key, None)
            seen.add(key)
            continue
        out.append(line)
    if pending:
        if out and out[-1].strip():
            out.append("")
        if ENV_COMMENT not in out:
            out.append(ENV_COMMENT)
        out.extend(f"{k}={format_env_value(v)}" for k, v in pending.items())
    return "\n".join(out) + "\n"


def wrapper_script(tool: Path, values: Mapping[str, str]) -> str:
    """A ``sh`` wrapper running ``tool`` with ``values`` set (``LD_LIBRARY_PATH`` prepended)."""
    lines = [
        "#!/bin/sh",
        f"{WRAPPER_MARKER}: runs the user-level unixODBC {tool.name}.",
    ]
    lines += [f"ODBCSYSINI={shlex.quote(values['ODBCSYSINI'])}", "export ODBCSYSINI"]
    if values.get("LD_LIBRARY_PATH"):
        lib = shlex.quote(values["LD_LIBRARY_PATH"])
        lines += [
            f"LD_LIBRARY_PATH={lib}" + "${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}",
            "export LD_LIBRARY_PATH",
        ]
    lines.append(f'exec {shlex.quote(str(tool))} "$@"')
    return "\n".join(lines) + "\n"


def write_wrappers(
    prefix: Path, bin_dir: Path, values: Mapping[str, str]
) -> tuple[list[Path], list[str]]:
    """Write wrappers for the unixODBC tools this install provides; return them and any warnings."""
    written: list[Path] = []
    warnings: list[str] = []
    for name in WRAPPED_TOOLS:
        tool = prefix / "usr" / "bin" / name
        if not tool.exists():
            continue
        path = bin_dir / name
        if path.exists() and WRAPPER_MARKER not in path.read_text(errors="replace"):
            warnings.append(f"{path} exists and is not ours; left it alone.")
            continue
        bin_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(wrapper_script(tool, values))
        path.chmod(0o755)
        written.append(path)
    return written, warnings


def environment_warnings(
    values: Mapping[str, str],
    environ: Mapping[str, str],
    bin_dir: Path,
    wrote_wrappers: bool,
) -> list[str]:
    """What in the current environment would stop the worker seeing this install."""
    warnings = []
    for key, value in values.items():
        current = environ.get(key)
        if not current or not value:
            continue
        if key == "LD_LIBRARY_PATH":
            if _paths(value) <= _paths(current):
                continue
            needed = f"{value}:{current}"
        elif current == value:
            continue
        else:
            needed = value
        warnings.append(
            f"{key} is already set in your environment, and scai keeps it over .env. "
            f"Set it to {needed} where it is defined, then restart the app."
        )
    path_dirs = [
        os.path.normpath(p) for p in environ.get("PATH", "").split(os.pathsep) if p
    ]
    if wrote_wrappers and os.path.normpath(str(bin_dir)) not in path_dirs:
        warnings.append(
            f"{bin_dir} is not on PATH; the odbcinst/isql wrappers there are reachable only by full path."
        )
    return warnings


_LOAD_DRIVER = "import ctypes, sys; ctypes.CDLL(sys.argv[1])"


def verify(
    odbcinst: Path | None,
    driver: Path,
    values: Mapping[str, str],
    run: Runner = subprocess.run,
) -> list[str]:
    """Problems found loading the driver through this install (empty when it works)."""
    env = dict(os.environ)
    env.update({k: v for k, v in values.items() if v})
    if values.get("LD_LIBRARY_PATH") and os.environ.get("LD_LIBRARY_PATH"):
        env["LD_LIBRARY_PATH"] = (
            f"{values['LD_LIBRARY_PATH']}:{os.environ['LD_LIBRARY_PATH']}"
        )
    problems = []
    loaded = run(
        [sys.executable, "-c", _LOAD_DRIVER, str(driver)],
        capture_output=True,
        text=True,
        env=env,
    )
    if loaded.returncode != 0:
        missing: list[str] = []
        if shutil.which("ldd"):
            linked = run(["ldd", str(driver)], capture_output=True, text=True, env=env)
            missing = sorted(
                {
                    ln.split("=>")[0].strip()
                    for ln in linked.stdout.splitlines()
                    if "not found" in ln
                }
            )
        if missing:
            problems.append(
                "The driver cannot find these libraries: " + ", ".join(missing)
            )
        else:
            problems.append(f"The driver does not load: {_tail(loaded)}")
    tool = str(odbcinst) if odbcinst and odbcinst.exists() else shutil.which("odbcinst")
    if tool:
        listed = run([tool, "-q", "-d"], capture_output=True, text=True, env=env)
        if f"[{DRIVER_NAME}]" not in listed.stdout:
            problems.append(f"odbcinst does not list {DRIVER_NAME}: {_tail(listed)}")
    return problems


@dataclass
class Result:
    driver: Path
    env: dict[str, str]
    env_file: Path | None
    wrappers: list[Path]
    warnings: list[str]
    problems: list[str]


def _write_project_env(
    project_dir: Path, values: Mapping[str, str], prefix: Path
) -> Path:
    env_file = project_dir / ".env"
    existing = env_file.read_text() if env_file.exists() else ""
    env_file.write_text(
        upsert_env(existing, merge_env_values(values, read_env(existing), prefix))
    )
    return env_file


def _replace_prefix(staging: Path, prefix: Path) -> None:
    """Swap the new install in, refusing to delete a directory this script did not make."""
    if prefix.exists():
        if any(prefix.iterdir()) and not (prefix / PREFIX_MARKER).exists():
            raise InstallError(
                f"{prefix} is not empty and was not made by this script; pass another --prefix."
            )
        shutil.rmtree(prefix)
    staging.rename(prefix)


def install(
    prefix: Path,
    project_dir: Path | None,
    bin_dir: Path,
    fields: Mapping[str, str],
    repo_override: str | None = None,
    run: Runner = subprocess.run,
    get: Callable[[str], bytes] = http_get,
    machine: str | None = None,
) -> Result:
    """Fetch, unpack and wire up unixODBC + msodbcsql18 under ``prefix``."""
    target = resolve_target(fields, repo_override)
    arch = machine_arch(target.family, machine)
    if (
        prefix.exists()
        and any(prefix.iterdir())
        and not (prefix / PREFIX_MARKER).exists()
    ):
        raise InstallError(
            f"{prefix} is not empty and was not made by this script; pass another --prefix."
        )
    prefix.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="scai-odbc-") as tmp:
        workdir = Path(tmp)
        # Unpacked beside the prefix so a failed run leaves a working install in place.
        staging = Path(
            tempfile.mkdtemp(prefix=f".{prefix.name}-", dir=str(prefix.parent))
        )
        try:
            if target.family == "deb":
                driver_pkg, depends = fetch_driver_deb(target, arch, workdir, get)
                for pkg in [*fetch_unixodbc_deb(depends, workdir, run), driver_pkg]:
                    extract_deb(pkg, staging, run)
            else:
                driver_pkg = fetch_driver_rpm(target, arch, workdir, get)
                for pkg in [*fetch_unixodbc_rpm(workdir, run), driver_pkg]:
                    extract_rpm(pkg, staging, run)
            find_driver(staging)
            (staging / PREFIX_MARKER).write_text("Installed by install_odbc_user.py\n")
            _replace_prefix(staging, prefix)
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    driver = find_driver(prefix)
    (prefix / "etc").mkdir(parents=True, exist_ok=True)
    (prefix / "etc" / "odbcinst.ini").write_text(odbcinst_ini(driver))
    values = env_values(prefix, library_dirs(prefix))
    env_file = (
        _write_project_env(project_dir, values, prefix)
        if project_dir is not None
        else None
    )
    wrappers, warnings = write_wrappers(prefix, bin_dir, values)
    warnings += environment_warnings(values, os.environ, bin_dir, bool(wrappers))
    problems = verify(prefix / "usr" / "bin" / "odbcinst", driver, values, run)
    return Result(driver, values, env_file, wrappers, warnings, problems)


def _paths(value: str) -> set[str]:
    return {os.path.normpath(p) for p in value.split(":") if p}


def project_env_problems(
    values: Mapping[str, str],
    project_env: Mapping[str, str],
    environ: Mapping[str, str],
    env_file: Path,
) -> list[str]:
    """What the project's ``.env`` fails to give the worker of ``values``.

    A variable already set in ``environ`` is skipped: scai keeps it over ``.env``,
    and :func:`environment_warnings` judges it.
    """
    lacking = []
    sysini = values["ODBCSYSINI"]
    if not environ.get("ODBCSYSINI") and _paths(
        project_env.get("ODBCSYSINI", "")
    ) != _paths(sysini):
        lacking.append("ODBCSYSINI")
    lib = values.get("LD_LIBRARY_PATH", "")
    if (
        lib
        and not environ.get("LD_LIBRARY_PATH")
        and not _paths(lib) <= _paths(project_env.get("LD_LIBRARY_PATH", ""))
    ):
        lacking.append("LD_LIBRARY_PATH")
    if not lacking:
        return []
    return [
        (
            f"{env_file} does not point the worker at this install ({', '.join(lacking)}); "
            "run the install for this project."
        )
    ]


def check(
    prefix: Path, project_dir: Path | None, run: Runner = subprocess.run
) -> list[str]:
    """Problems with an existing install, and with what the worker's environment would make of it.

    The worker gets the real environment, then the project's ``.env`` for whatever
    that leaves unset, so both are checked against the install.
    """
    driver = find_driver(prefix)
    values = env_values(prefix, library_dirs(prefix))
    problems = verify(prefix / "usr" / "bin" / "odbcinst", driver, values, run)
    problems += environment_warnings(values, os.environ, prefix, wrote_wrappers=False)
    if project_dir is not None:
        env_file = project_dir / ".env"
        current = read_env(env_file.read_text()) if env_file.exists() else {}
        problems += project_env_problems(values, current, os.environ, env_file)
    return problems


_SQLSERVER_DRIVER = re.compile(r"^\[(ODBC Driver \d+ for SQL Server)\]", re.MULTILINE)


def system_driver(run: Runner = subprocess.run) -> str | None:
    """The SQL Server driver the system's own ``odbcinst`` lists, passing over this script's wrappers."""
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        tool = Path(directory or ".") / "odbcinst"
        if not (tool.is_file() and os.access(tool, os.X_OK)):
            continue
        if WRAPPER_MARKER.encode() in tool.read_bytes():
            continue
        listed = run([str(tool), "-q", "-d"], capture_output=True, text=True)
        found = _SQLSERVER_DRIVER.search(listed.stdout or "")
        return found.group(1) if found else None
    return None


def preflight(
    prefix: Path, project_dir: Path | None, run: Runner = subprocess.run
) -> tuple[list[str], str]:
    """``--check``: the problems, and the line to print when there are none.

    A user-level install, when there is one, is checked for this project whatever
    ``odbcinst`` says: its wrappers list the driver for every project, configured or not.
    Without one, the system's own ``odbcinst`` decides.
    """
    if (prefix / PREFIX_MARKER).exists():
        return check(prefix, project_dir, run), "OK: the driver loads."
    found = system_driver(run)
    if found:
        return [], f"OK: the system's {found} is installed."
    return [
        f"No ODBC Driver for SQL Server: the system has none, and there is no user-level install under {prefix}."
    ], ""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--accept-eula",
        action="store_true",
        help=f"accept Microsoft's ODBC Driver 18 licence ({EULA_URL})",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify a user-level install for --project-dir, or else the system's driver; downloads nothing",
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        help="migration project whose .env gets ODBCSYSINI and LD_LIBRARY_PATH",
    )
    parser.add_argument(
        "--prefix",
        type=Path,
        default=DEFAULT_PREFIX,
        help=f"install location (default {DEFAULT_PREFIX})",
    )
    parser.add_argument(
        "--bin-dir",
        type=Path,
        default=DEFAULT_BIN_DIR,
        help=f"where the odbcinst/isql wrappers go (default {DEFAULT_BIN_DIR})",
    )
    parser.add_argument(
        "--ms-repo",
        help="Microsoft package repository URL, for a distribution the script does not map itself",
    )
    return parser


def _report(problems: Sequence[str], ok: str = "OK: the driver loads.") -> int:
    for problem in problems:
        print(f"FAILED: {problem}", file=sys.stderr)
    if problems:
        return 1
    print(ok)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.check and not args.accept_eula:
        print(
            f"Microsoft ODBC Driver 18 for SQL Server is licensed under {EULA_URL}.\n"
            "Re-run with --accept-eula once you have read and accepted it. Nothing was installed.",
            file=sys.stderr,
        )
        return 2
    if not sys.platform.startswith("linux"):
        print(
            "This script installs on Linux only; on macOS use Homebrew (msodbcsql18).",
            file=sys.stderr,
        )
        return 1
    if args.project_dir is not None and not args.project_dir.is_dir():
        print(f"--project-dir {args.project_dir} is not a directory.", file=sys.stderr)
        return 1
    prefix = args.prefix.expanduser().resolve()
    project_dir = args.project_dir.resolve() if args.project_dir is not None else None
    try:
        if args.check:
            return _report(*preflight(prefix, project_dir))
        try:
            fields = parse_os_release(Path("/etc/os-release").read_text())
        except OSError:
            fields = {}
        result = install(
            prefix, project_dir, args.bin_dir.expanduser(), fields, args.ms_repo
        )
    except (
        InstallError,
        subprocess.CalledProcessError,
        OSError,
        tarfile.TarError,
    ) as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        if not args.check:
            print(OTHER_ROUTES, file=sys.stderr)
        return 1

    print(f"Installed {DRIVER_NAME} under {prefix}")
    print(f"  driver: {result.driver}")
    for key, value in result.env.items():
        print(f"  {key}={value}")
    print(
        f"  written to {result.env_file}"
        if result.env_file
        else "  no --project-dir: set these in the worker's environment"
    )
    for wrapper in result.wrappers:
        print(f"  wrapper: {wrapper}")
    for warning in result.warnings:
        print(f"WARNING: {warning}")
    return _report(result.problems)


if __name__ == "__main__":
    sys.exit(main())
