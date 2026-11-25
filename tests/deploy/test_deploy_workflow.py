"""deploy.yml'nin yapısı (K-140). İş GitHub'da çalışır; burada yalnız CI'dan geçen `main` push'unun
ya da elle verilen bir SHA'nın, sabit bir komutla Pi'ye gittiği ve günlüğe cihaza özel bir şey
yazılmadığı denetlenir."""

import re
import shlex
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

import guncelle

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
DEPLOY = WORKFLOWS / "deploy.yml"
USES = re.compile(r"^\s*(?:-\s+)?uses:\s*(\S+)(.*)$", re.MULTILINE)
SECRET = re.compile(r"\$\{\{\s*secrets\.(\w+)\s*\}\}")
SAMPLE = "0123456789abcdef0123456789abcdef01234567"


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


def _step(name: str) -> dict[str, Any]:
    steps: list[dict[str, Any]] = [step for step in _job()["steps"] if step.get("name") == name]
    [step] = steps
    return step


def _uses(prefix: str) -> dict[str, Any]:
    steps: list[dict[str, Any]] = [
        step for step in _job()["steps"] if step.get("uses", "").startswith(f"{prefix}@")
    ]
    [step] = steps
    return step


def test_a_completed_ci_run_on_main_or_a_manual_sha_triggers_a_deploy() -> None:
    ci = _load(WORKFLOWS / "ci.yml")
    triggers = _triggers(_load(DEPLOY))

    assert set(triggers) == {"workflow_run", "workflow_dispatch"}
    assert triggers["workflow_run"] == {
        "workflows": [ci["name"]],
        "types": ["completed"],
        "branches": ["main"],
    }
    assert triggers["workflow_dispatch"]["inputs"] == {
        "sha": {
            "description": "Kurulacak commit (40 haneli, main'de)",
            "required": True,
            "type": "string",
        },
        "geri": {
            "description": "Geriye dönüşe izin ver",
            "required": False,
            "type": "boolean",
            "default": False,
        },
    }
    assert _triggers(ci)["push"] == {"branches": ["main"]}


def test_an_automatic_run_needs_a_successful_push_to_main_in_this_repository() -> None:
    """Fork'tan gelen ve dalı `main` adını taşıyan bir PR çalışması da `workflow_run`'ı tetikler."""
    manual, automatic = (part.strip() for part in _job()["if"].split(" || "))

    assert manual == "github.event_name == 'workflow_dispatch'"
    assert automatic.startswith("(")
    assert automatic.endswith(")")
    assert {part.strip() for part in automatic[1:-1].split("&&")} == {
        "github.event.workflow_run.conclusion == 'success'",
        "github.event.workflow_run.event == 'push'",
        "github.event.workflow_run.head_branch == 'main'",
        "github.event.workflow_run.head_repository.full_name == github.repository",
    }


def test_a_deploy_reads_only_the_code_and_is_never_cut_short() -> None:
    workflow = _load(DEPLOY)
    job = _job()

    assert list(workflow["jobs"]) == ["deploy"]
    assert workflow["permissions"] == job["permissions"] == {"contents": "read"}
    assert job["environment"] == "production"
    assert workflow["concurrency"] == {"group": "deploy-production", "cancel-in-progress": False}
    assert job["timeout-minutes"] * 60 > 2 * guncelle.JOB_WAIT
    assert job["env"] == {
        "SHA": "${{ github.event_name == 'workflow_dispatch' && inputs.sha "
        "|| github.event.workflow_run.head_sha }}",
        "GERI": "${{ github.event_name == 'workflow_dispatch' && inputs.geri || false }}",
    }
    assert _uses("actions/checkout")["with"] == {
        "ref": "${{ env.SHA }}",
        "persist-credentials": False,
    }


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
        "RPI_HOST",
        "RPI_USER",
        "RPI_SSH_KEY",
        "RPI_KNOWN_HOSTS",
    }
    assert "vars." not in text
    assert "ts.net" not in text
    assert "secrets." not in (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")


def test_the_tailnet_node_is_tagged_ci_without_cache_or_ping() -> None:
    """`ping` çıktısı cihazın adını ve adresini yazardı; önbelleğe main'deki CI işleri yazabilir."""
    assert _uses("tailscale/github-action")["with"] == {
        "oauth-client-id": "${{ secrets.TS_OAUTH_CLIENT_ID }}",
        "oauth-secret": "${{ secrets.TS_OAUTH_SECRET }}",
        "tags": "tag:ci",
        "version": "1.104.4",
        "use-cache": "false",
        "log-mode": "quiet",
    }


def test_the_frontend_is_built_only_if_it_exists_and_without_a_cache() -> None:
    node = _uses("actions/setup-node")
    build = _step("Ön yüzü derle")

    assert node["if"] == build["if"] == "steps.on-yuz.outputs.var == 'true'"
    assert node["with"] == {
        "node-version-file": "frontend/.nvmrc",
        "package-manager-cache": "false",
    }
    assert build["working-directory"] == "frontend"
    assert build["run"].splitlines() == [
        "npm ci",
        "npm run build",
        'tar -C dist -czf "$RUNNER_TEMP/on-yuz.tar.gz" .',
    ]
    assert "frontend/package.json" in _step("Ön yüz var mı")["run"]


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


def test_the_pi_gets_only_the_update_command_over_a_pinned_host_key() -> None:
    script = _step("Pi'de güncelle")["run"]
    arguments = _ssh_arguments(script)
    options = {arguments[index + 1] for index, value in enumerate(arguments) if value == "-o"}

    assert script.startswith('[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || {')
    assert _step("SHA denetimi")["run"].startswith('[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || {')
    assert {
        "BatchMode=yes",
        "StrictHostKeyChecking=yes",
        "GlobalKnownHostsFile=/dev/null",
        "IdentitiesOnly=yes",
        "AddressFamily=inet",
    } <= options
    assert arguments[-4:] == ["$RPI_USER@$RPI_HOST", "$command", "<", "$package"]


def test_the_remote_command_is_one_the_update_script_accepts() -> None:
    script = _step("Pi'de güncelle")["run"]
    base = re.search(r'^command="(sudo \S+) \$SHA"$', script, re.MULTILINE)
    assert base is not None
    assert base.group(1) == f"sudo {guncelle.URETIM.betik}"
    assert 'command="$command --geri"' in script
    assert 'command="$command --paket -"' in script

    for extra in ([], ["--geri"], ["--paket", "-"], ["--geri", "--paket", "-"]):
        assert guncelle.parse_args([SAMPLE, *extra]) is not None


def test_the_job_ends_with_the_pis_exit_code() -> None:
    """0 kuruldu ya da zaten kurulu; 1-4 betiğin kodları; gerisi SSH'nin ya da sudo'nun."""
    script = _step("Pi'de güncelle")["run"]

    assert script.rstrip().endswith('exit "$code"')
    assert [int(code) for code in re.findall(r"^\s+(\d)\) ", script, re.MULTILINE)] == [
        code.value for code in guncelle.Kod
    ]
