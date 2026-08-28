#!/usr/bin/env python3
"""Deterministically compress and independently verify the 202608272155 JSON shards."""
from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import importlib.util
import json
import shutil
import tempfile
from pathlib import Path

GENERATION = "202608272155"
RESUME_GENERATION = "202608280630"
MAXIMUM_FILE_BYTES = 90_000_000
MAXIMUM_TOTAL_BYTES = 200_000_000
MAXIMUM_EXPANDED_SHARD_BYTES = 64_000_000
MAXIMUM_EXPANDED_TOTAL_BYTES = 500_000_000
MAXIMUM_COMPRESSION_RATIO = 250
CONTENT_ENCODING = "gzip"
PARENT_PATH = Path(__file__).with_name("202608272155-verify-companies-house-candidate.py")

spec = importlib.util.spec_from_file_location("companies_verify_202608272155_for_0630", PARENT_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("Unable to load the pinned 202608272155 verifier")
BASE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(BASE)


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def canonical_manifest(value: dict) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def candidate_files(root: Path) -> list[Path]:
    nodes = list(root.rglob("*"))
    if any(path.is_symlink() for path in nodes):
        raise RuntimeError("Candidate contains a symlink")
    return sorted(path for path in nodes if path.is_file())


def decompress_bounded(path: Path) -> bytes:
    chunks: list[bytes] = []
    total = 0
    with gzip.open(path, "rb") as handle:
        while True:
            chunk = handle.read(min(1024 * 1024, MAXIMUM_EXPANDED_SHARD_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAXIMUM_EXPANDED_SHARD_BYTES:
                raise RuntimeError(f"Expanded shard ceiling failed before full decompression: {path.name}")
    return b"".join(chunks)


def physical_totals(root: Path) -> tuple[int, list[str]]:
    files = candidate_files(root)
    oversized = [f"{path.relative_to(root).as_posix()}={path.stat().st_size}" for path in files if path.stat().st_size > MAXIMUM_FILE_BYTES]
    return sum(path.stat().st_size for path in files), oversized


def compress(root: Path) -> dict:
    manifest_path = root / "manifest-v2.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("generation") != GENERATION or manifest.get("schema") != BASE.MANIFEST_SCHEMA:
        raise RuntimeError("Unexpected parent candidate manifest")
    expanded_total = 0
    for logical_name in sorted(BASE.EXPECTED_CARTRIDGES):
        entry = manifest["cartridges"][logical_name]
        policy = entry["shard_policy"]
        if policy != BASE.SHARD_POLICY:
            raise RuntimeError(f"Unexpected parent shard policy: {logical_name}")
        entry["shard_policy"] = {
            **policy,
            "content_encoding": CONTENT_ENCODING,
            "maximum_compression_ratio": MAXIMUM_COMPRESSION_RATIO,
        }
        for receipt in entry["shards"]:
            relative = receipt["path"]
            source = root / relative
            expanded = source.read_bytes()
            if len(expanded) != receipt["bytes"] or digest_bytes(expanded) != receipt["sha256"]:
                raise RuntimeError(f"Parent shard receipt drifted: {relative}")
            if len(expanded) > MAXIMUM_EXPANDED_SHARD_BYTES:
                raise RuntimeError(f"Expanded shard ceiling failed: {relative}")
            encoded = gzip.compress(expanded, compresslevel=9, mtime=0)
            if not encoded or len(expanded) > len(encoded) * MAXIMUM_COMPRESSION_RATIO:
                raise RuntimeError(f"Compression ratio ceiling failed: {relative}")
            target = source.with_suffix(source.suffix + ".gz")
            if target.exists():
                raise RuntimeError(f"Compressed target already exists: {target.name}")
            target.write_bytes(encoded)
            source.unlink()
            receipt.update(
                {
                    "path": relative + ".gz",
                    "bytes": len(encoded),
                    "sha256": digest_bytes(encoded),
                    "expanded_bytes": len(expanded),
                    "expanded_sha256": digest_bytes(expanded),
                    "content_encoding": CONTENT_ENCODING,
                    "maximum_compression_ratio": MAXIMUM_COMPRESSION_RATIO,
                }
            )
            expanded_total += len(expanded)
    if expanded_total > MAXIMUM_EXPANDED_TOTAL_BYTES:
        raise RuntimeError(f"Expanded candidate JSON ceiling failed: {expanded_total}")
    manifest["schema"] = "companies-house-bounded-candidate-v3"
    manifest["filing_truth_caveat"] = "Companies House filings are public-register statements and are not independently verified facts."
    manifest["third_party_rights_caveat"] = "Third-party rights and data-protection duties apply independently of the source licences and Ventus usage context."
    manifest["data_discipline"].update(
        {
            "logical_json_content_encoding": CONTENT_ENCODING,
            "expanded_json_shard_maximum_bytes": MAXIMUM_EXPANDED_SHARD_BYTES,
            "expanded_json_total_maximum_bytes": MAXIMUM_EXPANDED_TOTAL_BYTES,
            "maximum_json_compression_ratio": MAXIMUM_COMPRESSION_RATIO,
        }
    )
    manifest["candidate_outputs"].update(
        {
            "logical_json_content_encoding": CONTENT_ENCODING,
            "expanded_json_shard_maximum_bytes": MAXIMUM_EXPANDED_SHARD_BYTES,
            "expanded_json_total_maximum_bytes": MAXIMUM_EXPANDED_TOTAL_BYTES,
            "maximum_json_compression_ratio": MAXIMUM_COMPRESSION_RATIO,
        }
    )
    manifest_path.write_bytes(canonical_manifest(manifest))
    return verify(root)


def verify(root: Path) -> dict:
    errors: list[str] = []
    companies = 0
    try:
        manifest_path = root / "manifest-v2.json"
        manifest = json.loads(manifest_path.read_text())
        if manifest_path.read_bytes() != canonical_manifest(manifest):
            raise RuntimeError("Compressed manifest canonical byte closure failed")
        if manifest.get("schema") != "companies-house-bounded-candidate-v3" or manifest.get("generation") != GENERATION:
            raise RuntimeError("Compressed manifest identity failed")
        if manifest.get("usage_context") != "NON_COMMERCIAL_OPEN_SOURCE" or manifest.get("source_rights_are_distinct_from_usage_context") is not True:
            raise RuntimeError("Usage context and source-rights separation failed")
        if not manifest.get("filing_truth_caveat") or not manifest.get("third_party_rights_caveat"):
            raise RuntimeError("Independent filing-truth or third-party-rights caveat is missing")
        expected_compression = {
            "logical_json_content_encoding": CONTENT_ENCODING,
            "expanded_json_shard_maximum_bytes": MAXIMUM_EXPANDED_SHARD_BYTES,
            "expanded_json_total_maximum_bytes": MAXIMUM_EXPANDED_TOTAL_BYTES,
            "maximum_json_compression_ratio": MAXIMUM_COMPRESSION_RATIO,
        }
        if any(manifest.get("data_discipline", {}).get(key) != value for key, value in expected_compression.items()):
            raise RuntimeError("Compressed data-discipline declaration failed")
        if any(manifest.get("candidate_outputs", {}).get(key) != value for key, value in expected_compression.items()):
            raise RuntimeError("Compressed candidate-output declaration failed")
        total, oversized = physical_totals(root)
        if oversized or total > MAXIMUM_TOTAL_BYTES:
            raise RuntimeError(f"Physical publication ceiling failed: total={total}, oversized={oversized}")
        expanded_total = 0
        with tempfile.TemporaryDirectory(prefix="companies-expanded-") as temp_name:
            expanded_root = Path(temp_name)
            synthetic = copy.deepcopy(manifest)
            synthetic["schema"] = BASE.MANIFEST_SCHEMA
            synthetic.pop("filing_truth_caveat", None)
            synthetic.pop("third_party_rights_caveat", None)
            for name in sorted(BASE.EXPECTED_CARTRIDGES):
                physical_entry = manifest["cartridges"][name]
                synthetic_entry = synthetic["cartridges"][name]
                expected_policy = {
                    **BASE.SHARD_POLICY,
                    "content_encoding": CONTENT_ENCODING,
                    "maximum_compression_ratio": MAXIMUM_COMPRESSION_RATIO,
                }
                if physical_entry.get("shard_policy") != expected_policy:
                    raise RuntimeError(f"Compressed shard policy failed: {name}")
                synthetic_entry["shard_policy"] = copy.deepcopy(BASE.SHARD_POLICY)
                previous_last = None
                for physical_receipt, synthetic_receipt in zip(physical_entry["shards"], synthetic_entry["shards"]):
                    relative = physical_receipt["path"]
                    if not relative.endswith(".json.gz"):
                        raise RuntimeError(f"Compressed shard suffix failed: {relative}")
                    source = root / relative
                    if source.is_symlink() or not source.is_file() or not source.resolve().is_relative_to(root.resolve()):
                        raise RuntimeError(f"Compressed shard path failed: {relative}")
                    encoded = source.read_bytes()
                    if len(encoded) != physical_receipt["bytes"] or digest_bytes(encoded) != physical_receipt["sha256"]:
                        raise RuntimeError(f"Compressed shard receipt failed: {relative}")
                    if len(encoded) < 10 or encoded[:2] != b"\x1f\x8b" or encoded[4:8] != b"\x00\x00\x00\x00":
                        raise RuntimeError(f"Deterministic gzip header failed: {relative}")
                    expanded = decompress_bounded(source)
                    if len(expanded) != physical_receipt["expanded_bytes"] or digest_bytes(expanded) != physical_receipt["expanded_sha256"]:
                        raise RuntimeError(f"Expanded shard receipt failed: {relative}")
                    if len(expanded) > MAXIMUM_EXPANDED_SHARD_BYTES or len(expanded) > len(encoded) * MAXIMUM_COMPRESSION_RATIO:
                        raise RuntimeError(f"Expanded shard bound failed: {relative}")
                    expanded_total += len(expanded)
                    plain_relative = relative[:-3]
                    target = expanded_root / plain_relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(expanded)
                    for key in ("expanded_bytes", "expanded_sha256", "content_encoding", "maximum_compression_ratio"):
                        synthetic_receipt.pop(key, None)
                    synthetic_receipt.update({"path": plain_relative, "bytes": len(expanded), "sha256": digest_bytes(expanded)})
                    if previous_last is not None and physical_receipt["first_company_number"] <= previous_last:
                        raise RuntimeError(f"Compressed shard range order failed: {relative}")
                    previous_last = physical_receipt["last_company_number"]
            if expanded_total > MAXIMUM_EXPANDED_TOTAL_BYTES:
                raise RuntimeError(f"Expanded candidate JSON ceiling failed: {expanded_total}")
            for path in candidate_files(root):
                relative = path.relative_to(root)
                if relative.as_posix() == "manifest-v2.json" or relative.as_posix().endswith(".json.gz"):
                    continue
                target = expanded_root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
            synthetic["data_discipline"] = copy.deepcopy(BASE.DATA_DISCIPLINE)
            synthetic["candidate_outputs"] = {
                key: value
                for key, value in synthetic["candidate_outputs"].items()
                if key not in {
                    "logical_json_content_encoding",
                    "expanded_json_shard_maximum_bytes",
                    "expanded_json_total_maximum_bytes",
                    "maximum_json_compression_ratio",
                }
            }
            synthetic["candidate_outputs"]["maximum_candidate_total_bytes"] = MAXIMUM_EXPANDED_TOTAL_BYTES
            expanded_manifest = expanded_root / "manifest-v2.json"
            expanded_manifest.write_bytes(canonical_manifest(synthetic))
            old_limit = BASE.MAXIMUM_TOTAL_BYTES
            old_discipline = BASE.DATA_DISCIPLINE
            try:
                BASE.MAXIMUM_TOTAL_BYTES = MAXIMUM_EXPANDED_TOTAL_BYTES
                BASE.DATA_DISCIPLINE = copy.deepcopy(synthetic["data_discipline"])
                BASE.DATA_DISCIPLINE["candidate_total_maximum_bytes"] = MAXIMUM_EXPANDED_TOTAL_BYTES
                synthetic["data_discipline"] = copy.deepcopy(BASE.DATA_DISCIPLINE)
                expanded_manifest.write_bytes(canonical_manifest(synthetic))
                inherited = BASE.verify(expanded_root)
            finally:
                BASE.MAXIMUM_TOTAL_BYTES = old_limit
                BASE.DATA_DISCIPLINE = old_discipline
            if inherited.get("status") != "PASS":
                raise RuntimeError(f"Expanded JSON to ZSTD Parquet semantic readback failed: {inherited.get('errors')}")
            companies = int(inherited["companies"])
        expected = {"manifest-v2.json"}
        expected.update(row["path"] for entry in manifest["cartridges"].values() for row in entry["shards"])
        expected.update(row["path"] for row in manifest["evidence"])
        expected.update([manifest["analytical_dataset"]["file"]["path"], manifest["relationship_dataset"]["file"]["path"]])
        expected.update(row["path"] for row in manifest["audits"])
        actual = {path.relative_to(root).as_posix() for path in candidate_files(root)}
        if actual != expected:
            raise RuntimeError("Compressed candidate exact file closure failed")
    except Exception as exc:
        errors.append(str(exc))
    total, oversized = physical_totals(root) if root.exists() else (0, [])
    return {
        "schema": "companies-house-bounded-verification-v6",
        "generation": GENERATION,
        "resume_generation": RESUME_GENERATION,
        "status": "FAIL" if errors else "PASS",
        "companies": companies,
        "bytes_monitor": total,
        "maximum_candidate_total_bytes": MAXIMUM_TOTAL_BYTES,
        "maximum_expanded_json_total_bytes": MAXIMUM_EXPANDED_TOTAL_BYTES,
        "maximum_compression_ratio": MAXIMUM_COMPRESSION_RATIO,
        "oversized_files": oversized,
        "errors": errors[:100],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--compress", action="store_true")
    mode.add_argument("--verify", action="store_true")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = compress(args.input) if args.compress else verify(args.input)
    except Exception as exc:
        total, oversized = physical_totals(args.input) if args.input.exists() else (0, [])
        result = {
            "schema": "companies-house-bounded-verification-v6",
            "generation": GENERATION,
            "resume_generation": RESUME_GENERATION,
            "status": "FAIL",
            "companies": 0,
            "bytes_monitor": total,
            "maximum_candidate_total_bytes": MAXIMUM_TOTAL_BYTES,
            "maximum_expanded_json_total_bytes": MAXIMUM_EXPANDED_TOTAL_BYTES,
            "maximum_compression_ratio": MAXIMUM_COMPRESSION_RATIO,
            "oversized_files": oversized,
            "errors": [f"compression: {exc}"],
        }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_bytes(canonical_manifest(result))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
