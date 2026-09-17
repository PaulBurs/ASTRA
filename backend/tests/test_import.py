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
