from fastapi.testclient import TestClient

from main import app


client = TestClient(app)


def test_xlsx_import():
    files = {
        "file": (
            "test.xlsx",
            b"fake excel content",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    }

    response = client.post(
        "/api/import",
        files=files,
    )

    assert response.status_code == 200

    data = response.json()

    assert data["status"] == "success"
    assert data["filename"] == "test.xlsx"
    
    
def test_csv_import():
    response = client.post(
        "/api/import",
        files={
            "file": (
                "history.csv",
                b"timestamp,value\n2026-01-01,25.0\n",
                "text/csv",
            )
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["status"] == "success"
    assert data["filename"] == "history.csv"
    assert data["size_bytes"] > 0
