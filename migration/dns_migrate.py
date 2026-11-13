#!/usr/bin/env python3
"""Export a TransIP zone, prepare a mijn.host zonefile, and verify publication."""

import argparse
from collections import defaultdict
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

GENERATED = {"SOA", "DNSKEY", "RRSIG", "NSEC", "NSEC3", "NSEC3PARAM", "CDS", "CDNSKEY"}
SUPPORTED = {"A", "AAAA", "CNAME", "MX", "TXT", "SRV", "CAA", "TLSA", "SSHFP", "NS"}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def domain_name(value):
    domain = value.rstrip(".").lower().encode("idna").decode("ascii")
    if not re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+", domain):
        raise ValueError("Expected a domain name")
    return domain


def export(domain):
    token = Path(os.environ["TRANSIP_TOKEN_FILE"]).read_text().strip()
    if not token or any(char.isspace() for char in token):
        raise ValueError("Expected one TransIP v6 bearer token")
    request = Request(
        f"https://api.transip.nl/v6/domains/{domain}/dns",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    with build_opener(NoRedirect()).open(request, timeout=20) as response:
        return {"domain": domain, "transip": json.load(response)}


def records(zone):
    domain = domain_name(zone["domain"])
    apex = domain + "."
    for row in zone["transip"]["dnsEntries"]:
        name = row["name"].lower()
        if name in ("", "@", domain, apex):
            name = apex
        elif not name.endswith("."):
            name = name + "." if name.endswith("." + domain) else name + "." + apex
        if (name != apex and not name.endswith("." + apex)) or not re.fullmatch(
            r"(?:\*\.)?[a-z0-9_.-]+\.", name
        ):
            raise ValueError(f"Invalid owner {name}")
        kind = row["type"].upper()
        if kind in GENERATED or (name == apex and kind == "NS"):
            continue
        if kind not in SUPPORTED:
            raise ValueError(f"Review unsupported record {name} {kind} before migration")
        ttl = row["expire"]
        value = row["content"]
        if type(ttl) is not int or not 0 < ttl <= 2147483647:
            raise ValueError(f"Invalid TTL for {name}")
        if not isinstance(value, str) or any(ord(char) < 32 for char in value):
            raise ValueError(f"Invalid record value for {name}")
        if kind == "TXT" and not value.startswith('"'):
            data = value.encode()
            value = " ".join(
                '"' + "".join(
                    chr(byte) if 32 <= byte <= 126 and byte not in (34, 92) else f"\\{byte:03d}"
                    for byte in data[offset:offset + 255]
                ) + '"'
                for offset in range(0, max(1, len(data)), 255)
            )
        elif kind in ("CNAME", "MX", "NS", "SRV"):
            fields = value.split()
            if not fields:
                raise ValueError(f"Missing target for {name}")
            fields[-1] = fields[-1].rstrip(".") + "."
            value = " ".join(fields)
        yield name, ttl, kind, value


def canonical(kind, value):
    if kind == "TXT":
        # Decode DNS presentation escapes and join TXT character strings.
        chunks = re.findall(r'"((?:\\.|[^"\\])*)"', value)
        if not chunks:
            raise ValueError("Expected quoted TXT data")
        return re.sub(r"\\(\d{3}|.)",
                      lambda m: chr(int(m[1])) if len(m[1]) == 3 and m[1].isdigit() else m[1],
                      "".join(chunks))
    if kind == "TLSA":
        return "".join(value.split()).lower()
    if kind in ("AAAA", "A"):
        from ipaddress import ip_address
        return str(ip_address(value))
    if kind in ("CNAME", "MX", "NS", "SRV"):
        return " ".join(value.lower().split()).rstrip(".")
    return tuple(shlex.split(value))


def check(rows, servers):
    expected = defaultdict(set)
    for name, _, kind, value in rows:
        expected[name, kind].add(canonical(kind, value))
    failures = 0
    for server in servers:
        previous_failures = failures
        for (name, kind), values in sorted(expected.items()):
            result = subprocess.run(
                ["dig", "@" + server, name, kind, "+norecurse", "+noall", "+comments",
                 "+answer", "+time=3", "+tries=1"],
                capture_output=True, text=True,
            )
            actual = set()
            for line in result.stdout.splitlines():
                fields = line.split(maxsplit=4)
                if len(fields) == 5 and fields[0].lower() == name and fields[3] == kind:
                    actual.add(canonical(kind, fields[4]))
            authoritative = re.search(r"^;; flags: [^;]*\baa\b", result.stdout, re.M)
            if result.returncode or not authoritative or values != actual:
                print(f"{server}: mismatch or no authoritative answer for {name} {kind}")
                failures += 1
        if failures == previous_failures:
            print(f"{server}: exported RRsets match")
    return bool(failures)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    cmd = commands.add_parser("export")
    cmd.add_argument("domain", type=domain_name)
    cmd.add_argument("output", type=Path)
    cmd = commands.add_parser("zonefile")
    cmd.add_argument("source", type=Path)
    cmd.add_argument("output", type=Path)
    cmd = commands.add_parser("check")
    cmd.add_argument("source", type=Path)
    cmd.add_argument("--server", action="append", required=True)
    args = parser.parse_args()
    try:
        if args.command == "export":
            data = export(args.domain)
            with args.output.open("x") as output:
                json.dump(data, output, indent=2)
            return 0
        rows = sorted(set(records(json.loads(args.source.read_text()))))
        if not rows:
            raise ValueError("Source zone has no transferable records")
        if args.command == "check":
            return int(check(rows, args.server))
        with args.output.open("x") as output:
            for name, ttl, kind, value in rows:
                output.write(f"{name} {ttl} IN {kind} {value}\n")
        return 0
    except HTTPError as error:
        parser.exit(1, f"TransIP API returned HTTP {error.code}\n")
    except (ValueError, OSError, KeyError) as error:
        parser.exit(1, f"Migration stopped: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
