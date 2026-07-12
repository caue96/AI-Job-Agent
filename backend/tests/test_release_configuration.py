from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_local_services_are_bound_to_loopback():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    frontend_package = (ROOT / "frontend" / "package.json").read_text(encoding="utf-8")

    assert '"127.0.0.1:8000:8000"' in compose
    assert '"127.0.0.1:5173:8080"' in compose
    assert "vite --host 127.0.0.1" in frontend_package
    assert "vite --host 0.0.0.0" not in frontend_package


def test_backend_runtime_image_is_minimal_and_unprivileged():
    dockerfile = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (ROOT / "backend" / ".dockerignore").read_text(encoding="utf-8")

    assert "pip install --no-cache-dir .\n" in dockerfile
    assert ".[dev]" not in dockerfile
    assert "USER app" in dockerfile
    assert ".env" in dockerignore
    assert ".deps/" in dockerignore


def test_frontend_build_context_excludes_local_artifacts():
    dockerignore = (ROOT / "frontend" / ".dockerignore").read_text(encoding="utf-8")

    assert "node_modules/" in dockerignore
    assert "dist/" in dockerignore
    assert ".env" in dockerignore
