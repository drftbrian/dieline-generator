def test_health_creates_database(client, tmp_path):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "database": "ok"}
    assert (tmp_path / "dieline.db").exists()


def test_unknown_route_uses_error_shape(client):
    res = client.get("/api/nope")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "NOT_FOUND"


def test_api_error_shape(client):
    from app.errors import ApiError

    @client.app.get("/api/_boom")
    def boom():
        raise ApiError(400, "PDF_ENCRYPTED", "암호로 보호된 PDF입니다.", hint="보호를 해제하세요.")

    res = client.get("/api/_boom")
    assert res.status_code == 400
    assert res.json() == {
        "error": {
            "code": "PDF_ENCRYPTED",
            "message": "암호로 보호된 PDF입니다.",
            "hint": "보호를 해제하세요.",
            "details": {},
        }
    }
