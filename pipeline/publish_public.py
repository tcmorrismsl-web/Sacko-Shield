#!/usr/bin/env python3
"""Publish a freshly built data set to the public GitHub copy, safely.

Used by the scheduled Claude data refresh after it rebuilds the data:

    python3 pipeline/publish_public.py --data /path/to/built/app/data

1. copies players.json, schedule.json and picks.json into app/data
2. writes app/data/meta.json with every league-specific field removed
3. copies the private leagues.json into app/data (git-ignored) so the leak
   guard below and the public build both have it
4. builds index.html with build_standalone.py --public
5. scans every file git would commit for any league name, team name, manager
   name or league ID from leagues.json, and exits non-zero (nothing is staged)
   if one is found

It never commits or pushes; the caller does that only if this exits 0.
"""
import argparse, json, pathlib, re, shutil, subprocess, sys

REPO = pathlib.Path(__file__).resolve().parent.parent
DATA = REPO / "app" / "data"
PUBLIC = ["players.json", "schedule.json", "picks.json"]
META_PRIVATE = ["league_verification", "build_note"]


def private_terms(leagues):
    terms = set()
    for lg in leagues:
        terms |= {lg.get("name"), str(lg.get("league_id") or "")}
        for r in lg.get("rosters", []):
            terms |= {r.get("name"), r.get("owner")}
            # first names inside team names: "Pat's Team" -> "Pat"
            m = re.match(r"([A-Z][a-z]+)'s?\b", r.get("name") or "")
            if m:
                terms.add(m.group(1))
    return {t for t in terms if t and len(t) >= 4}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="folder holding the freshly built *.json")
    a = ap.parse_args()
    src = pathlib.Path(a.data)

    for name in PUBLIC:
        shutil.copyfile(src / name, DATA / name)
    meta = json.loads((src / "meta.json").read_text())
    for k in META_PRIVATE:
        meta.pop(k, None)
    (DATA / "meta.json").write_text(json.dumps(meta, separators=(",", ":"), allow_nan=False))
    if (src / "leagues.json").exists() and (src / "leagues.json").resolve() != (DATA / "leagues.json").resolve():
        shutil.copyfile(src / "leagues.json", DATA / "leagues.json")

    subprocess.run([sys.executable, str(REPO / "pipeline" / "build_standalone.py"),
                    "--app", str(REPO / "app"), "--out", str(REPO / "index.html"), "--public"],
                   check=True)

    leagues = json.loads((DATA / "leagues.json").read_text()) if (DATA / "leagues.json").exists() else []
    terms = private_terms(leagues)
    files = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                           cwd=REPO, capture_output=True, text=True, check=True).stdout.split()
    # public phrases that contain a private first name by coincidence
    allow = ["Levi's Stadium"]
    leaks = []
    for f in files:
        p = REPO / f
        if not p.is_file() or p.suffix.lower() in (".png", ".jpg", ".ico"):
            continue
        text = p.read_text(errors="ignore")
        for phrase in allow:
            text = text.replace(phrase, "")
        for t in terms:
            if re.search(r"(?<![A-Za-z0-9])" + re.escape(t) + r"(?![A-Za-z0-9])", text):
                leaks.append((f, t))
    if leaks:
        print(f"REFUSED: {len(leaks)} private name/ID hits in files git would publish:")
        for f, t in sorted(set(leaks))[:30]:
            print(f"  {f}: {t!r}")
        sys.exit(2)
    print(f"ok: {len(files)} files scanned against {len(terms)} private terms, no hits")


if __name__ == "__main__":
    main()
