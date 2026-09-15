"""Marg ERP hook sync kit for Nexus Inventory Platform.

This script intentionally reuses the existing CSV upload API. Marg exports raw
CSV files from hooks/run-commands, this script converts them to the platform's
standard CSV templates, uploads them in dependency order, and exits.
"""

from __future__ import annotations

import argparse
import csv
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

DEFAULT_BASE_URL = "http://127.0.0.1:8000/api/v1"
DEFAULT_WORK_DIR = Path(r"C:\marg-sync")
DEFAULT_LOCATION = "Main"

STANDARD_HEADERS = {
    "products": [
        "SKU Code",
        "Product Name",
        "Category",
        "UOM",
        "Unit Cost",
        "Selling Price",
    ],
    "batches": ["SKU Code", "Batch No", "MFD", "EXP", "Quantity", "Location"],
    "transactions": [
        "SKU Code",
        "Location",
        "Transaction Type",
        "Quantity",
        "Unit Cost",
        "Reference No",
        "Transaction Date",
    ],
}


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    log_path = args.work_dir / "logs" / "nexus-inventory-marg-sync.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        if not args.token and (not args.email or not args.password):
            raise RuntimeError(
                "Set NEXUS_TOKEN, or set both NEXUS_EMAIL and NEXUS_PASSWORD."
            )
        token = args.token or login(args.base_url, args.email, args.password)

        if args.command == "status":
            print("logged_in")
            return 0

        outputs = prepare_standard_csvs(args.work_dir, args.default_location)
        selected = _selected_entities(args.command, outputs)

        if not selected:
            raise RuntimeError("No Marg exports found to upload.")

        jobs: list[dict] = []
        for entity_type, path in selected:
            job = upload_csv(args.base_url, token, entity_type, path)
            jobs.append({"entity_type": entity_type, **job})
            if args.poll:
                poll_status(args.base_url, token, str(job["job_id"]))

        _log(log_path, {"status": "ok", "jobs": jobs})
        print(json.dumps({"status": "ok", "jobs": jobs}, indent=2))
        return 0
    except Exception as exc:
        _log(log_path, {"status": "error", "error": str(exc)})
        print(f"Nexus Inventory Platform Marg sync failed: {exc}", file=sys.stderr)
        return 1


def prepare_standard_csvs(
    work_dir: Path, default_location: str = DEFAULT_LOCATION
) -> dict[str, Path]:
    """Convert Marg raw exports into standard Nexus CSV files."""
    out_dir = work_dir / "nexus"
    out_dir.mkdir(parents=True, exist_ok=True)

    outputs: dict[str, Path] = {}

    products_src = work_dir / "pro_full.csv"
    if products_src.exists():
        products = transform_product_rows(_read_csv(products_src))
        outputs["products"] = out_dir / "products.csv"
        _write_csv(outputs["products"], STANDARD_HEADERS["products"], products)

    batches_src = work_dir / "probat_full.csv"
    if batches_src.exists():
        batches = transform_batch_rows(_read_csv(batches_src), default_location)
        outputs["batches"] = out_dir / "batches.csv"
        _write_csv(outputs["batches"], STANDARD_HEADERS["batches"], batches)

    transactions_src = _first_existing(
        work_dir / "dis_full.csv",
        work_dir / "dis_sample.csv",
    )
    if transactions_src:
        transactions = transform_transaction_rows(
            _read_csv(transactions_src), default_location
        )
        outputs["transactions"] = out_dir / "transactions.csv"
        _write_csv(
            outputs["transactions"], STANDARD_HEADERS["transactions"], transactions
        )

    return outputs


def transform_product_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    transformed: list[dict[str, str]] = []
    for row in rows:
        sku = _clean(row.get("code"))
        name = _clean(row.get("name") or row.get("billname"))
        if not sku or not name:
            continue
        transformed.append(
            {
                "SKU Code": sku,
                "Product Name": name,
                "Category": _clean(row.get("product")),
                "UOM": _clean(row.get("unit")) or "PCS",
                "Unit Cost": _clean(row.get("prate")),
                "Selling Price": _clean(row.get("mrp")),
            }
        )
    return transformed


def transform_batch_rows(
    rows: list[dict[str, str]], default_location: str = DEFAULT_LOCATION
) -> list[dict[str, str]]:
    transformed: list[dict[str, str]] = []
    for row in rows:
        sku = _clean(row.get("code"))
        batch_no = _clean(row.get("batchno") or row.get("mybatch"))
        if not sku or not batch_no:
            continue
        transformed.append(
            {
                "SKU Code": sku,
                "Batch No": batch_no,
                "MFD": _clean_date(row.get("mfd")),
                "EXP": _clean_date(row.get("exp")),
                "Quantity": _clean(row.get("balance")),
                "Location": _clean(row.get("godwon")) or default_location,
            }
        )
    return transformed


def transform_transaction_rows(
    rows: list[dict[str, str]], default_location: str = DEFAULT_LOCATION
) -> list[dict[str, str]]:
    transformed: list[dict[str, str]] = []
    for row in rows:
        sku = _clean(row.get("code"))
        qty = _clean(row.get("qty"))
        tx_date = _clean_date(row.get("date"))
        if not sku or not qty or not tx_date:
            continue
        transformed.append(
            {
                "SKU Code": sku,
                "Location": _clean(row.get("godwon")) or default_location,
                "Transaction Type": "out",
                "Quantity": qty,
                "Unit Cost": _clean(row.get("rate")),
                "Reference No": _clean(row.get("vcn") or row.get("voucher")),
                "Transaction Date": tx_date,
            }
        )
    return transformed


def login(base_url: str, email: str, password: str) -> str:
    data = urllib.parse.urlencode(
        {"username": email, "password": password, "grant_type": "password"}
    ).encode()
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/auth/login",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    return str(_json(request)["access_token"])


def upload_csv(base_url: str, token: str, entity_type: str, path: Path) -> dict:
    body, content_type = _multipart({"entity_type": entity_type}, "file", path)
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/integrations/upload",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": content_type,
        },
        method="POST",
    )
    return _json(request)


def poll_status(base_url: str, token: str, job_id: str) -> dict:
    last_payload: dict | None = None
    for _ in range(90):
        request = urllib.request.Request(
            f"{base_url.rstrip('/')}/integrations/upload/{job_id}/status",
            headers={"Authorization": f"Bearer {token}"},
            method="GET",
        )
        last_payload = _json(request)
        if last_payload["status"] in {"completed", "failed"}:
            if last_payload["status"] == "failed":
                raise RuntimeError(f"Sync job failed: {last_payload}")
            return last_payload
        time.sleep(2)
    raise TimeoutError(f"Timed out waiting for sync job {job_id}: {last_payload}")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync Marg CSV exports to Nexus Inventory Platform"
    )
    parser.add_argument(
        "command",
        choices=[
            "status",
            "sync-all",
            "sync-products",
            "sync-batches",
            "sync-transactions",
        ],
        help="Action to run.",
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("NEXUS_BASE_URL", DEFAULT_BASE_URL),
        help="Nexus API base URL ending in /api/v1.",
    )
    parser.add_argument(
        "--email",
        default=os.getenv("NEXUS_EMAIL", ""),
        help="Nexus username/email.",
    )
    parser.add_argument(
        "--password",
        default=os.getenv("NEXUS_PASSWORD", ""),
        help="Nexus password.",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("NEXUS_TOKEN", ""),
        help="Optional existing access token.",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=Path(os.getenv("MARG_SYNC_DIR", str(DEFAULT_WORK_DIR))),
        help="Directory containing Marg raw CSV exports.",
    )
    parser.add_argument(
        "--default-location",
        default=os.getenv("MARG_DEFAULT_LOCATION", DEFAULT_LOCATION),
        help="Location name used when Marg row has no godown.",
    )
    parser.add_argument(
        "--no-poll",
        action="store_false",
        dest="poll",
        help="Return after upload is accepted instead of waiting for processing.",
    )
    parser.set_defaults(poll=True)
    return parser.parse_args(argv)


def _selected_entities(
    command: str, outputs: dict[str, Path]
) -> list[tuple[str, Path]]:
    if command == "sync-products":
        order = ["products"]
    elif command == "sync-batches":
        order = ["batches"]
    elif command == "sync-transactions":
        order = ["transactions"]
    else:
        order = ["products", "batches", "transactions"]
    return [(entity, outputs[entity]) for entity in order if entity in outputs]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, headers: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def _clean(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text in {"-  -", "- -", "nan", "NaN", "None"} else text


def _clean_date(value: object) -> str:
    return _clean(value)


def _first_existing(*paths: Path) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def _json(request: urllib.request.Request) -> dict:
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc


def _multipart(
    fields: dict[str, str], file_field: str, path: Path
) -> tuple[bytes, str]:
    boundary = f"----nexus-marg-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                str(value).encode(),
                b"\r\n",
            ]
        )

    mime_type = mimetypes.guess_type(path.name)[0] or "text/csv"
    chunks.extend(
        [
            f"--{boundary}\r\n".encode(),
            (
                f'Content-Disposition: form-data; name="{file_field}"; '
                f'filename="{path.name}"\r\n'
            ).encode(),
            f"Content-Type: {mime_type}\r\n\r\n".encode(),
            path.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _log(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"time": time.time(), **payload}) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
