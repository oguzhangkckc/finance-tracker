"""deploy.yml'nin yapısı (K-132). İş GitHub'da çalışır; burada yalnız CI'dan geçen `main` push'unun,
onayla ve yalnız SHA olarak Pi'ye gittiği denetlenir."""

import re
import shlex
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

import istek

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
DEPLOY = WORKFLOWS / "deploy.yml"
USES = re.compile(r"^\s*(?:-\s+)?uses:\s*(\S+)(.*)$", re.MULTILINE)
SECRET = re.compile(r"\$\{\{\s*secrets\.(\w+)\s*\}\}")


def _load(path: Path) -> dict[Any, Any]:
    workflow: dict[Any, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return workflow


def _triggers(workflow: dict[Any, Any]) -> dict[str, Any]:
    """YAML 1.1'de `on` anahtarı `True` olarak okunur."""
    triggers: dict[str, Any] = workflow[True]
    return triggers


def _job() -> dict[str, Any]:
    job: dict[str, Any] = _load(DEPLOY)["jobs"]["deploy"]
    return job


def _deploy_step() -> dict[str, Any]:
    steps: list[dict[str, Any]] = [step for step in _job()["steps"] if "run" in step]
    [step] = steps
    return step


def test_only_a_completed_ci_run_on_main_triggers_a_deploy() -> None:
    ci = _load(WORKFLOWS / "ci.yml")

    assert _triggers(_load(DEPLOY)) == {
        "workflow_run": {"workflows": [ci["name"]], "types": ["completed"], "branches": ["main"]}
    }
    assert _triggers(ci)["push"] == {"branches": ["main"]}


def test_the_job_runs_only_for_a_successful_push_to_main_in_this_repository() -> None:
    """Fork'tan gelen ve dalı `main` adını taşıyan bir PR çalışması da `workflow_run`'ı tetikler."""
    condition = _job()["if"]

    assert "||" not in condition
    assert {part.strip() for part in condition.split("&&")} == {
        "github.event.workflow_run.conclusion == 'success'",
        "github.event.workflow_run.event == 'push'",
        "github.event.workflow_run.head_branch == 'main'",
        "github.event.workflow_run.head_repository.full_name == github.repository",
    }


def test_a_deploy_needs_approval_reads_nothing_and_is_never_cut_short() -> None:
    workflow = _load(DEPLOY)
    job = _job()

    assert list(workflow["jobs"]) == ["deploy"]
    assert workflow["permissions"] == job["permissions"] == {"contents": "read"}
    assert job["environment"] == "production"
    assert workflow["concurrency"] == {"group": "deploy-production", "cancel-in-progress": False}
    assert not any("actions/checkout" in step.get("uses", "") for step in job["steps"])
    assert job["timeout-minutes"] * 60 > istek.WAIT_SECONDS


def test_no_workflow_runs_pull_request_code_with_the_repositorys_rights() -> None:
    assert [
        path.name for path in WORKFLOWS.glob("*.yml") if "pull_request_target" in path.read_text()
    ] == []


def test_every_action_is_pinned_to_a_commit_with_its_version_noted() -> None:
    found = [
        (path.name, action, note)
        for path in sorted(WORKFLOWS.glob("*.yml"))
        for action, note in USES.findall(path.read_text(encoding="utf-8"))
    ]

    assert {name for name, _, _ in found} == {"ci.yml", "deploy.yml"}
    for name, action, note in found:
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", action), (name, action)
        assert re.fullmatch(r"\s+# v\d+(\.\d+)*", note), (name, action)


def test_device_details_are_secrets_so_neither_the_repo_nor_the_public_log_shows_them() -> None:
    """Herkese açık depoda environment değişkenleri iş günlüğünde görünür; secret'lar maskelenir."""
    text = DEPLOY.read_text(encoding="utf-8")

    assert set(SECRET.findall(text)) == {
        "TS_OAUTH_CLIENT_ID",
        "TS_OAUTH_SECRET",
        "DEPLOY_SSH_KEY",
        "DEPLOY_HOST",
        "DEPLOY_KNOWN_HOSTS",
    }
    assert "vars." not in text
    assert "ts.net" not in text
    assert "secrets." not in (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")


def test_the_tailnet_node_is_tagged_ci_without_cache_or_ping() -> None:
    """`ping` çıktısı cihazın adını ve adresini yazardı; önbelleğe main'deki CI işleri yazabilir."""
    [tailscale] = [
        step
        for step in _job()["steps"]
        if step.get("uses", "").startswith("tailscale/github-action@")
    ]

    assert tailscale["with"] == {
        "oauth-client-id": "${{ secrets.TS_OAUTH_CLIENT_ID }}",
        "oauth-secret": "${{ secrets.TS_OAUTH_SECRET }}",
        "tags": "tag:ci",
        "version": "1.104.4",
        "use-cache": "false",
        "log-mode": "quiet",
    }


def test_expressions_reach_scripts_only_through_the_environment() -> None:
    """`${{ }}` `run` içinde olsaydı değeri kabuk kodu olarak çalışırdı."""
    for path in WORKFLOWS.glob("*.yml"):
        for job in _load(path)["jobs"].values():
            assert all("${{" not in step.get("run", "") for step in job["steps"]), path.name


def _ssh_arguments(script: str) -> list[str]:
    lines = script.splitlines()
    start = next(index for index, line in enumerate(lines) if line.startswith("ssh "))
    command: list[str] = []
    for line in lines[start:]:
        command.append(line.strip().removesuffix("\\"))
        if not line.endswith("\\"):
            break
    arguments = shlex.split(" ".join(command))
    return arguments[: arguments.index("||")]


def test_the_pi_gets_only_the_deploy_command_over_a_pinned_host_key() -> None:
    step = _deploy_step()
    arguments = _ssh_arguments(step["run"])
    options = {arguments[index + 1] for index, value in enumerate(arguments) if value == "-o"}
    sha = "0123456789abcdef0123456789abcdef01234567"

    assert step["env"]["SHA"] == "${{ github.event.workflow_run.head_sha }}"
    assert step["run"].startswith('[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || {')
    assert {
        "BatchMode=yes",
        "StrictHostKeyChecking=yes",
        "GlobalKnownHostsFile=/dev/null",
        "IdentitiesOnly=yes",
    } <= options
    assert arguments[-2] == "finans-deploy@$DEPLOY_HOST"
    assert istek.requested_sha(arguments[-1].replace("$SHA", sha)) == sha


def test_the_job_ends_with_the_pis_exit_code() -> None:
    """0 kuruldu (zaten kurulu ya da dondurulmuş da); 1-4 `istek`'in kodları; gerisi SSH'nin."""
    script = _deploy_step()["run"]

    assert script.rstrip().endswith('exit "$code"')
    assert [int(code) for code in re.findall(r"^\s+(\d)\) ", script, re.MULTILINE)] == [
        code.value for code in istek.Kod
    ]
