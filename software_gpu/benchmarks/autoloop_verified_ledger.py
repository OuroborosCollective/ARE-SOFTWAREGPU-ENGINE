"""Verify full, CI-attested CPU run receipts against a versioned candidate catalog.

The ledger records only identifiers. Caller MUST fetch the actual GitHub run and
artifact independently; no boolean or hash supplied by the agent is trusted.
"""
import hashlib
import json
import re
from .autoloop_cpu_ab import adjudicate, check_diff_scope

SHA40 = re.compile(r"[0-9a-f]{40}\Z")
SHA64 = re.compile(r"[0-9a-f]{64}\Z")
START = "<!-- ARE_CPU_RUN_LEDGER_BEGIN -->"
END = "<!-- ARE_CPU_RUN_LEDGER_END -->"
REPO = "OuroborosCollective/ARE-SOFTWAREGPU-ENGINE"
WORKFLOW = "Autoloop CPU A/B (GitHub runner only)"

def need(value, message):
    if not value:
        raise ValueError(message)

def parse_markdown_ledger(content):
    begin = content.count(START)
    end = content.count(END)
    if not begin and not end:
        return None
    need(begin == 1 and end == 1 and content.index(START) < content.index(END), "LEDGER_MARKERS")
    raw = content.split(START,1)[1].split(END,1)[0].strip()
    need(len(raw.encode()) <= 256000, "LEDGER_TOO_LARGE")
    document = json.loads(raw)
    need(isinstance(document, dict), "LEDGER_FORMAT")
    return document

def _validated_outcome(item, proof):
    need(set(proof)=={"run","receipt"}, "PROOF_FIELDS")
    run, r = proof["run"], proof["receipt"]
    need(run.get("id")==item["run_id"], "CI_RUN_ID")
    need(run.get("repository", {}).get("full_name")==REPO, "CI_REPOSITORY")
    need(run.get("name")==WORKFLOW, "CI_WORKFLOW")
    need(run.get("event")=="workflow_dispatch", "CI_EVENT")
    need(run.get("status")=="completed" and run.get("conclusion")=="success", "CI_NOT_GREEN")
    need(run.get("run_attempt")==1, "CI_RETRY_REQUIRES_EXPLICIT_EVIDENCE")
    need(r.get("protocol")=="are.autoloop-cpu-ab-run.v1", "RECEIPT_PROTOCOL")
    need(r.get("smoke_only") is False and r.get("candidate_dirty_shader") is False, "FULL_RUN_REQUIRED")
    need(bool(SHA40.fullmatch(str(r.get("source_commit")))) and
         bool(SHA40.fullmatch(str(r.get("baseline_commit")))), "SOURCE_COMMIT")
    need(run.get("head_sha")==r["source_commit"], "CI_HEAD")
    digest=r.get("sha256")
    body={k:v for k,v in r.items() if k!="sha256"}
    expected=hashlib.sha256(json.dumps(body,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
    need(bool(SHA64.fullmatch(str(digest))) and digest==expected, "RECEIPT_DIGEST")
    check_diff_scope(r.get("baseline_source_sha256"),r.get("source_sha256"))
    need(r.get("render_scope")=="whole-draw CPU RGBA8 plus float32 depth", "RENDER_SCOPE")
    env=r.get("environment")
    need(isinstance(env,dict) and env.get("runner")=="github-hosted" and
         env.get("workers")==[1,2] and all(isinstance(env.get(k),str) and env[k] for k in ("cpu","python","numpy")), "RUNNER_ENV")
    result=adjudicate(r.get("profiles"))
    need(result["profile_count"]==20 and result["outcome"]==r.get("outcome"), "VERDICT_MISMATCH")
    need(r.get("profile_count")==20 and isinstance(r.get("score"),(int,float)) and
         abs(r["score"]-result["score"]) <= 1e-9, "SCORE_MISMATCH")
    return "accepted" if result["outcome"]=="accepted" else "rejected"

def verify_authenticated_runs(catalog, document, fetch_proof):
    need(catalog.get("protocol")=="are.autoloop-cpu-catalog.v1", "CATALOG_PROTOCOL")
    need(document.get("protocol")=="are.autoloop-cpu-run-ledger.v1" and
         document.get("catalog_version")==catalog.get("version"), "LEDGER_VERSION")
    candidates=catalog.get("candidates")
    need(isinstance(candidates,list) and candidates and len(set(candidates))==len(candidates), "CATALOG_CANDIDATES")
    entries=document.get("runs")
    need(isinstance(entries,list) and len(entries) <= len(candidates)*3*100, "LEDGER_SIZE")
    used_runs, seen=set(),set()
    sweeps={}
    for item in entries:
        need(isinstance(item,dict) and set(item)=={"sweep","candidate","run_id"}, "LEDGER_ENTRY_FIELDS")
        s,c,rid=item["sweep"],item["candidate"],item["run_id"]
        need(type(s) is int and s>0, "LEDGER_SWEEP")
        need(c in candidates, "LEDGER_CANDIDATE")
        need(type(rid) is int and rid>0, "LEDGER_RUN_ID")
        need(rid not in used_runs, "LEDGER_DUPLICATE_RUN")
        need((s,c) not in seen, "LEDGER_DUPLICATE_CANDIDATE")
        used_runs.add(rid);seen.add((s,c))
        sweeps.setdefault(s,{})[c]=_validated_outcome(item,fetch_proof(rid))
    streak=complete=0
    for n in range(1,max(sweeps,default=0)+1):
        if set(sweeps.get(n,{}))!=set(candidates):
            break
        complete=n
        streak=0 if "accepted" in sweeps[n].values() else streak+1
    return {"completed":streak>=3,"complete_sweeps":complete,
            "consecutive_no_gain_sweeps":streak,"candidate_count":len(candidates)}

def fetch_github_proof(run_id, token=None):
    """Independent GitHub API lookup and exact-run artifact readback.

    The uploaded artifact is NOT taken from agent-provided URLs or the
    scoreboard. GitHub run ID and attempt determine the one permitted name.
    """
    import io
    import os
    import urllib.request
    import zipfile

    need(type(run_id) is int and run_id > 0, "CI_RUN_ID")
    token = token if token is not None else os.environ.get("GITHUB_TOKEN", "")
    need(isinstance(token, str) and token, "CI_TOKEN_REQUIRED")
    prefix = "https://api.github.com/repos/" + REPO
    headers = {"Authorization": "Bearer " + token,
               "Accept": "application/vnd.github+json",
               "User-Agent": "ARE-Autoloop-Evidence-Verifier"}

    def request_json(url):
        need(url.startswith(prefix + "/"), "CI_URL_SCOPE")
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=15) as response:
            need(response.status == 200, "CI_HTTP_STATUS")
            body = response.read(1024 * 1024 + 1)
        need(len(body) <= 1024 * 1024, "CI_METADATA_TOO_LARGE")
        return json.loads(body)

    run = request_json(prefix + "/actions/runs/" + str(run_id))
    need(run.get("id") == run_id and run.get("run_attempt") == 1, "CI_RUN_ID")
    need(run.get("name") == WORKFLOW and run.get("event") == "workflow_dispatch", "CI_WORKFLOW")
    need(run.get("conclusion") == "success" and run.get("status") == "completed", "CI_NOT_GREEN")
    artifacts = request_json(prefix + "/actions/runs/" + str(run_id) + "/artifacts?per_page=100")
    need(artifacts.get("total_count") == 1 and len(artifacts.get("artifacts", [])) == 1, "CI_ARTIFACT_COUNT")
    artifact = artifacts["artifacts"][0]
    need(artifact.get("name") == f"are-autoloop-ab-{run_id}-1" and
         artifact.get("expired") is False and
         type(artifact.get("size_in_bytes")) is int and
         0 < artifact["size_in_bytes"] <= 8 * 1024 * 1024, "CI_ARTIFACT_IDENTITY")
    artifact_id = artifact.get("id")
    need(type(artifact_id) is int and artifact_id > 0, "CI_ARTIFACT_ID")
    url = prefix + "/actions/artifacts/" + str(artifact_id) + "/zip"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
        body = response.read(8 * 1024 * 1024 + 1)
    need(len(body) <= 8 * 1024 * 1024, "CI_ARTIFACT_ZIP_BUDGET")
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        names = archive.namelist()
        need(names == ["raw-600-pairs.json"], "CI_ARTIFACT_CONTENTS")
        info = archive.getinfo(names[0])
        need(0 < info.file_size <= 3 * 1024 * 1024, "CI_RECEIPT_SIZE")
        receipt = json.loads(archive.read(info))
    return {"run": run, "receipt": receipt}
