import unittest
from typing import Any, Dict, Optional

import optool


class MockResponse:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code
        self.text = str(payload)
        self.headers = {"content-type": "application/json"}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise optool.requests.HTTPError(f"HTTP {self.status_code}")

    def json(self) -> Any:
        return self.payload


class StubClient(optool.OpenPrescribingClient):
    def __init__(self, payloads: Dict[str, Any]) -> None:
        self.payloads = payloads
        super().__init__(request_get=self._get)

    def _get(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: int = 30,
    ):
        if url.endswith("bnf_code/"):
            return MockResponse(self.payloads["bnf_code"])
        if url.endswith("spending_by_org/"):
            return MockResponse(self.payloads["spending_by_org"])
        if url.endswith("org_details/"):
            return MockResponse(self.payloads["org_details"])
        raise AssertionError(f"Unexpected URL {url}")


class TestOptool(unittest.TestCase):
    def test_validate_bnf_uppercases(self) -> None:
        self.assertEqual(optool.validate_bnf_code("1304000h0aaaaaa"), "1304000H0AAAAAA")

    def test_validate_bnf_rejects_short(self) -> None:
        with self.assertRaises(optool.OpenPrescribingError):
            optool.validate_bnf_code("123")

    def test_rank_tie_prefers_first(self) -> None:
        rows = [
            optool.SpendingRow(date="2024-01-01", org_code="A", org_name="Alpha ICB", items=10),
            optool.SpendingRow(date="2024-01-01", org_code="B", org_name="Beta ICB", items=10),
            optool.SpendingRow(date="2024-02-01", org_code="B", org_name="Beta ICB", items=20),
        ]
        ranked = optool.rank_monthly_top_ics(rows)
        self.assertEqual(ranked, [("2024-01-01", "Alpha ICB"), ("2024-02-01", "Beta ICB")])

    def test_rank_weighted_uses_size(self) -> None:
        spending = [
            optool.SpendingRow(date="2024-01-01", org_code="A", org_name="Alpha ICB", items=100),
            optool.SpendingRow(date="2024-01-01", org_code="B", org_name="Beta ICB", items=90),
        ]
        sizes = [
            optool.OrgDetailRow(date="2024-01-01", org_code="A", org_name="Alpha ICB", total_list_size=1000),
            optool.OrgDetailRow(date="2024-01-01", org_code="B", org_name="Beta ICB", total_list_size=100),
        ]
        ranked = optool.rank_monthly_top_ics(spending, sizes)
        self.assertEqual(ranked, [("2024-01-01", "Beta ICB")])

    def test_run_with_stub(self) -> None:
        client = StubClient(
            {
                "bnf_code": [{"type": "chemical", "name": "Clobetasone butyrate"}],
                "spending_by_org": [
                    {
                        "date": "2024-01-01",
                        "row_id": "A",
                        "row_name": "Alpha ICB",
                        "items": 10,
                    },
                    {
                        "date": "2024-01-01",
                        "row_id": "B",
                        "row_name": "Beta ICB",
                        "items": 12,
                    },
                ],
                "org_details": [
                    {
                        "date": "2024-01-01",
                        "row_id": "A",
                        "row_name": "Alpha ICB",
                        "total_list_size": 100,
                    },
                    {
                        "date": "2024-01-01",
                        "row_id": "B",
                        "row_name": "Beta ICB",
                        "total_list_size": 200,
                    },
                ],
            }
        )
        lines = optool.run("1304000H0AAAAAA", weighted=True, client=client)
        self.assertEqual(lines, ["Clobetasone butyrate", "2024-01-01 Alpha ICB"])


if __name__ == "__main__":
    unittest.main()