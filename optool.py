from __future__ import annotations
import argparse
import sys
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

USER_AGENT = "bennett-institute-coding-problem-2026"
DEFAULT_BASE_URL = "https://openprescribing.net/api/1.0"
TIMEOUT_SECONDS = 30
RETRY_TOTAL = 3
RETRY_BACKOFF_FACTOR = 0.5
RETRY_STATUS_CODES = (429, 500, 502, 503, 504)


class OpenPrescribingError(RuntimeError):
    """Raised when the API cant satisfy user request."""


@dataclass(frozen=True)
class SpendingRow:
    date: str
    org_code: str
    org_name: str
    items: Decimal


@dataclass(frozen=True)
class OrgDetailRow:
    date: str
    org_code: str
    org_name: str
    total_list_size: Decimal


class OpenPrescribingClient:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        request_get: Optional[Callable[..., requests.Response]] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._session = self.build_session()
        self._request_get = request_get or self._session.get

    @staticmethod
    def build_session() -> requests.Session:
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "application/json, text/csv;q=0.9, */*;q=0.1",
            }
        )

        retry = Retry(
            total=RETRY_TOTAL,
            backoff_factor=RETRY_BACKOFF_FACTOR,
            status_forcelist=RETRY_STATUS_CODES,
            allowed_methods=frozenset({"GET"}),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "OpenPrescribingClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def get_json(self, path: str, params: Mapping[str, Any]) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            response = self._request_get(url, params=params, timeout=TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            raise OpenPrescribingError(
                "OpenPrescribing is not reachable. Please check your internet connection and try again."
            ) from exc

        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            detail = response.text.strip()
            message = f"OpenPrescribing returned HTTP {response.status_code}."
            if detail:
                message = f"{message} {detail}"
            raise OpenPrescribingError(message) from exc

        try:
            return response.json()
        except ValueError as exc:
            raise OpenPrescribingError(
                "OpenPrescribing returned data in an unexpected format."
            ) from exc

    def lookup_chemical_name(self, chemical_code: str) -> str:
        data = self.get_json(
            "bnf_code/",
            {"q": chemical_code, "exact": "true", "format": "json"},
        )
        if not isinstance(data, list):
            raise OpenPrescribingError("Unexpected response from the BNF code lookup.")

        for item in data:
            if isinstance(item, dict) and item.get("type") == "chemical":
                name = item.get("name")
                if isinstance(name, str) and name.strip():
                    return name.strip()

        raise OpenPrescribingError(
            f"No chemical substance was found for BNF code {chemical_code}."
        )

    @staticmethod
    def decimal(value: Any, field_name: str) -> Decimal:
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise OpenPrescribingError(
                f"OpenPrescribing returned an invalid {field_name} value."
            ) from exc

    def fetch_spending_by_org(self, chemical_code: str) -> List[SpendingRow]:
        data = self.get_json(
            "spending_by_org/",
            {"code": chemical_code, "org_type": "icb", "format": "json"},
        )
        if not isinstance(data, list):
            raise OpenPrescribingError(
                "Unexpected spending data returned by OpenPrescribing."
            )

        rows: List[SpendingRow] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                rows.append(
                    SpendingRow(
                        date=str(item["date"]),
                        org_code=str(item["row_id"]),
                        org_name=str(item["row_name"]),
                        items=self.decimal(item["items"], "items"),
                    )
                )
            except KeyError as exc:
                raise OpenPrescribingError(
                    "Spending data is missing a field we need (date, row_id, row_name, or items)."
                ) from exc
        return rows

    def fetch_org_details(self) -> List[OrgDetailRow]:
        data = self.get_json(
            "org_details/",
            {"org_type": "icb", "keys": "total_list_size", "format": "json"},
        )
        if not isinstance(data, list):
            raise OpenPrescribingError(
                "Unexpected organisation detail data returned by OpenPrescribing."
            )

        rows: List[OrgDetailRow] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            if "total_list_size" not in item:
                continue
            try:
                rows.append(
                    OrgDetailRow(
                        date=str(item["date"]),
                        org_code=str(item["row_id"]),
                        org_name=str(item["row_name"]),
                        total_list_size=self.decimal(
                            item["total_list_size"], "total_list_size"
                        ),
                    )
                )
            except KeyError as exc:
                raise OpenPrescribingError(
                    "Organisation details are missing a field(date, row_id, row_name or total_list_size)."
                ) from exc
        return rows


def validate_bnf_code(code: str) -> str:
    normalized = code.strip().upper()
    if len(normalized) != 15 or not normalized.isalnum():
        raise OpenPrescribingError(
            "Please provide a full 15-character BNF code made of letters and digits only."
        )
    return normalized


def chemical_code_from_bnf_code(code: str) -> str:
    return code[:9]


def rank_monthly_top_ics(
    spending_rows: Sequence[SpendingRow],
    list_size_rows: Optional[Sequence[OrgDetailRow]] = None,
) -> List[Tuple[str, str]]:
    list_size_lookup: Dict[Tuple[str, str], Decimal] = {}
    if list_size_rows is not None:
        for row in list_size_rows:
            list_size_lookup[(row.date, row.org_code)] = row.total_list_size

    by_month: Dict[str, List[SpendingRow]] = {}
    for row in spending_rows:
        by_month.setdefault(row.date, []).append(row)

    results: List[Tuple[str, str]] = []
    for month in sorted(by_month.keys(), key=date.fromisoformat):
        winner_name: Optional[str] = None
        winner_metric: Optional[Decimal] = None

        for row in by_month[month]:
            if list_size_rows is None:
                metric = row.items
            else:
                list_size = list_size_lookup.get((month, row.org_code))
                if list_size is None:
                    raise OpenPrescribingError(
                        f"Missing total list size for {row.org_name} in {month}."
                    )
                if list_size <= 0:
                    raise OpenPrescribingError(
                        f"Invalid total list size for {row.org_name} in {month}."
                    )
                metric = row.items / list_size

            if winner_metric is None or metric > winner_metric:
                winner_metric = metric
                winner_name = row.org_name

        if winner_name is None:
            raise OpenPrescribingError(f"No spending data available for {month}.")
        results.append((month, winner_name))

    return results

def run(
    code: str,
    weighted: bool,
    client: Optional[OpenPrescribingClient] = None,
) -> List[str]:
    normalized = validate_bnf_code(code)
    chemical_code = chemical_code_from_bnf_code(normalized)

    owns_client = client is None
    client = client or OpenPrescribingClient()
    try:
        chemical_name = client.lookup_chemical_name(chemical_code)
        spending_rows = client.fetch_spending_by_org(chemical_code)
        if not spending_rows:
            raise OpenPrescribingError(
                f"No ICB spending data was found for chemical code {chemical_code}."
            )

        list_size_rows = client.fetch_org_details() if weighted else None
        ranked = rank_monthly_top_ics(spending_rows, list_size_rows)
    finally:
        if owns_client:
            client.close()

    lines = [chemical_name]
    lines.extend(f"{month} {org_name}" for month, org_name in ranked)
    return lines


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="optool.py",
        description=(
            "Look up an OpenPrescribing chemical and the ICB with the highest monthly prescribing."
        ),
    )
    parser.add_argument("bnf_code", help="Full 15-character BNF code")
    parser.add_argument(
        "--weighted",
        action="store_true",
        help="Rank ICBs by items per patient using total list size.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        lines = run(args.bnf_code, args.weighted)
    except OpenPrescribingError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())