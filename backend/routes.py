"""All HTTP routes for the template Fit Scorer API."""
from __future__ import annotations

import csv
import http.client
import ipaddress
import io
import socket
import ssl
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from . import claude_agents, scoring
from .auth import AuthError, current_user, provision_user, require_admin, require_user
from .config import org_config, settings
from .db import get_db
from .models import (AuditLog, Decision, Feedback, Opportunity, Outcome,
                     Recalibration, Score, StrategyProfile, User)

router = APIRouter()

_BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
_MAX_REDIRECTS = 5
_MAX_REMOTE_BYTES = 2 * 1024 * 1024


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def get_active_profile(db: Session) -> StrategyProfile:
    p = db.query(StrategyProfile).filter(StrategyProfile.is_active == True).first()  # noqa: E712
    if p is None:
        p = db.query(StrategyProfile).order_by(desc(StrategyProfile.version)).first()
    if p is None:
        raise HTTPException(500, "No strategy profile found.")
    return p


def profile_to_dict(p: StrategyProfile) -> Dict[str, Any]:
    return {"version": p.version, "name": p.name, "profile_doc": p.profile_doc,
            "dimensions": p.dimensions, "hard_filters": p.hard_filters,
            "thresholds": p.thresholds, "tiers": p.tiers, "is_placeholder": p.is_placeholder}


def log(db: Session, actor: str, action: str, detail: Dict[str, Any]):
    db.add(AuditLog(actor=actor, action=action, detail=detail))
    db.commit()


def _resolve_public_http_url(url: str, resolver=socket.getaddrinfo):
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise HTTPException(400, "Enter a complete public http:// or https:// URL.")
    if parsed.username or parsed.password:
        raise HTTPException(400, "URLs containing credentials are not allowed.")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise HTTPException(400, "The URL contains an invalid port.") from exc

    try:
        literal = ipaddress.ip_address(parsed.hostname)
        addresses = [str(literal)]
    except ValueError:
        try:
            addresses = sorted({
                item[4][0]
                for item in resolver(parsed.hostname, port, type=socket.SOCK_STREAM)
            })
        except (OSError, ValueError) as exc:
            raise HTTPException(400, "That hostname could not be resolved.") from exc

    if not addresses:
        raise HTTPException(400, "That hostname could not be resolved.")
    try:
        checked = [ipaddress.ip_address(address) for address in addresses]
    except ValueError as exc:
        raise HTTPException(400, "That hostname returned an invalid address.") from exc
    if any(not address.is_global for address in checked):
        raise HTTPException(400, "Private, local, and reserved network addresses are not allowed.")
    return parsed, addresses, port


def validate_public_http_url(url: str, resolver=socket.getaddrinfo) -> str:
    parsed, _, _ = _resolve_public_http_url(url, resolver)
    return parsed.geturl()


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, hostname: str, address: str, port: int):
        super().__init__(hostname, port, timeout=25, context=ssl.create_default_context())
        self._address = address

    def connect(self):
        sock = socket.create_connection((self._address, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def _fetch_public_once(url: str):
    parsed, addresses, port = _resolve_public_http_url(url)
    address = addresses[0]
    if parsed.scheme == "https":
        connection = _PinnedHTTPSConnection(parsed.hostname, address, port)
    else:
        connection = http.client.HTTPConnection(address, port, timeout=25)
    target = parsed.path or "/"
    if parsed.query:
        target = f"{target}?{parsed.query}"
    headers = {**_BROWSER_HEADERS, "Host": parsed.netloc}
    try:
        connection.request("GET", target, headers=headers)
        response = connection.getresponse()
        body = response.read(_MAX_REMOTE_BYTES + 1)
        if len(body) > _MAX_REMOTE_BYTES:
            raise HTTPException(400, "The URL response is too large. Paste the text instead.")
        return response.status, dict(response.getheaders()), body, parsed.geturl()
    except HTTPException:
        raise
    except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
        raise HTTPException(400, "Could not fetch the URL. Paste the text instead.") from exc
    finally:
        connection.close()


def fetch_url_text(url: str) -> str:
    next_url = url
    for _ in range(_MAX_REDIRECTS + 1):
        status, headers, body, safe_url = _fetch_public_once(next_url)
        if status in (301, 302, 303, 307, 308):
            location = headers.get("Location") or headers.get("location")
            if not location:
                raise HTTPException(400, "The URL returned an invalid redirect.")
            next_url = urljoin(safe_url, location)
            continue
        if status >= 400:
            raise HTTPException(400, "Could not fetch the URL. Paste the text instead.")
        break
    else:
        raise HTTPException(400, "The URL redirected too many times.")

    ctype = headers.get("Content-Type", headers.get("content-type", "")).lower()
    if not any(t in ctype for t in ("html", "text", "xml")):
        raise HTTPException(400, f"The URL returned '{ctype or 'a non-text file'}'. Paste the text instead.")
    soup = BeautifulSoup(body.decode("utf-8", errors="replace"), "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    text = " ".join(soup.get_text(" ").split())
    if len(text) < 200:
        raise HTTPException(400, "The page returned too little text. Paste the text instead.")
    return text[:20000]


def extract_file_text(filename: str, data: bytes) -> str:
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader
        try:
            reader = PdfReader(io.BytesIO(data))
            text = "\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, f"Could not read that PDF: {e}. Paste the text instead.")
        if len(text.strip()) < 40:
            raise HTTPException(400, "That PDF has no selectable text (scanned/image-only). Paste the text.")
        return text[:20000]
    if name.endswith(".docx"):
        from docx import Document
        try:
            doc = Document(io.BytesIO(data))
            return "\n".join(p.text for p in doc.paragraphs)[:20000]
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, f"Could not read that Word file: {e}. Paste the text instead.")
    if name.endswith((".txt", ".md")):
        return data.decode("utf-8", errors="ignore")[:20000]
    raise HTTPException(400, "Unsupported file type. Upload a PDF, Word (.docx), or text file.")


def latest_score(db: Session, opp_id: str) -> Optional[Score]:
    return (db.query(Score).filter(Score.opportunity_id == opp_id)
            .order_by(desc(Score.created_at)).first())


def _serialize_opp(db: Session, opp: Opportunity, include_memo: bool = True) -> Dict[str, Any]:
    s = latest_score(db, opp.id)
    decision = (db.query(Decision).filter(Decision.opportunity_id == opp.id)
                .order_by(desc(Decision.decided_at)).first())
    outcome = (db.query(Outcome).filter(Outcome.opportunity_id == opp.id)
               .order_by(desc(Outcome.resolved_at)).first())
    fb = (db.query(Feedback).filter(Feedback.score_id == s.id).order_by(desc(Feedback.created_at)).first()
          if s else None)
    return {
        "id": opp.id, "title": opp.title, "created_at": opp.created_at.isoformat(),
        "parsed": opp.parsed, "variables": opp.variables,
        "score": None if not s else {
            "id": s.id, "overall_score": s.overall_score, "tier": s.tier, "confidence": s.confidence,
            "profile_version": s.profile_version, "dimension_scores": s.dimension_scores,
            "hard_filter_result": s.hard_filter_result,
            "memo_markdown": s.memo_markdown if include_memo else "", "model_used": s.model_used},
        "feedback": None if not fb else {"override_tier": fb.override_tier, "override_reason": fb.override_reason},
        "decision": None if not decision else decision.decision,
        "outcome": None if not outcome else {
            "outcome": outcome.outcome, "amount": outcome.amount,
            "final_funding_type": outcome.final_funding_type, "notes": outcome.notes},
    }


def run_and_store(db, user, text, source_type, source_url, variables) -> Dict[str, Any]:
    profile = get_active_profile(db)
    pdict = profile_to_dict(profile)
    if variables:
        pdict = {**pdict, "opportunity_variables": variables}
    result = scoring.score_pipeline(text, pdict)
    opp = Opportunity(submitted_by=user.id, source_type=source_type, source_url=source_url,
                      raw_text=text, title=result["parsed"].get("title", "Untitled")[:400],
                      parsed=result["parsed"], parse_confidence=result["parse_confidence"],
                      variables=variables or {})
    db.add(opp); db.commit(); db.refresh(opp)
    model_used = "mock" if settings.mock_mode else f"{settings.fast_model}+{settings.strong_model}"
    db.add(Score(opportunity_id=opp.id, profile_version=profile.version,
                 overall_score=result["overall_score"], tier=result["tier"],
                 dimension_scores=result["dimension_scores"], hard_filter_result=result["hard_filter_result"],
                 confidence=result["parse_confidence"], memo_markdown=result["memo_markdown"],
                 model_used=model_used))
    db.commit()
    log(db, user.email, "score_opportunity", {"opportunity_id": opp.id, "tier": result["tier"]})
    return _serialize_opp(db, opp)


# --------------------------------------------------------------------------
# Config + auth
# --------------------------------------------------------------------------
@router.get("/api/config")
def config(db: Session = Depends(get_db), user: Optional[User] = Depends(current_user)):
    placeholder = False
    try:
        placeholder = bool(get_active_profile(db).is_placeholder)
    except HTTPException:
        pass
    return {
        "org": {k: org_config.get(k) for k in
                ("org_name", "tool_name", "tagline", "brand_color", "brand_color_dark", "currency")},
        "mock_mode": settings.mock_mode, "google_oauth": settings.use_google_oauth,
        "dev_auth": settings.dev_auth, "profile_is_placeholder": placeholder,
        "user": None if not user else {"email": user.email, "name": user.name, "role": user.role},
    }


class DevLogin(BaseModel):
    email: str


@router.post("/api/dev-login")
def dev_login(body: DevLogin, request: Request, db: Session = Depends(get_db)):
    if settings.use_google_oauth or not settings.dev_auth:
        raise AuthError("Dev login is disabled. Use Google sign-in.", 403)
    user = provision_user(db, body.email)
    request.session["user_id"] = user.id
    return {"user": {"email": user.email, "name": user.name, "role": user.role}}


@router.post("/api/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


# --------------------------------------------------------------------------
# Opportunities
# --------------------------------------------------------------------------
class SubmitOpportunity(BaseModel):
    source_type: str
    text: Optional[str] = None
    url: Optional[str] = None
    variables: Dict[str, Any] = {}


@router.post("/api/opportunities")
def submit(body: SubmitOpportunity, db: Session = Depends(get_db), user: User = Depends(require_user)):
    if body.source_type == "url":
        if not body.url:
            raise HTTPException(400, "A URL is required.")
        text = fetch_url_text(body.url); source_url = body.url
    else:
        text = (body.text or "").strip(); source_url = ""
        if len(text) < 40:
            raise HTTPException(400, "Paste more of the opportunity text (at least a paragraph).")
    return run_and_store(db, user, text, body.source_type, source_url, body.variables)


@router.post("/api/opportunities/upload")
async def submit_file(file: UploadFile = File(...), warmth: str = Form(""),
                      db: Session = Depends(get_db), user: User = Depends(require_user)):
    data = await file.read()
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(400, "File larger than 15 MB. Upload a smaller file or paste the text.")
    text = extract_file_text(file.filename or "", data)
    variables = {"relationship_warmth": warmth} if warmth else {}
    return run_and_store(db, user, text, "file", file.filename or "upload", variables)


@router.get("/api/opportunities")
def list_opps(db: Session = Depends(get_db), user: User = Depends(require_user)):
    opps = db.query(Opportunity).order_by(desc(Opportunity.created_at)).limit(500).all()
    return [_serialize_opp(db, o, include_memo=False) for o in opps]


@router.get("/api/opportunities/{opp_id}")
def get_opp(opp_id: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    opp = db.query(Opportunity).filter(Opportunity.id == opp_id).first()
    if not opp:
        raise HTTPException(404, "Opportunity not found.")
    return _serialize_opp(db, opp)


@router.post("/api/opportunities/{opp_id}/rescore")
def rescore(opp_id: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    opp = db.query(Opportunity).filter(Opportunity.id == opp_id).first()
    if not opp:
        raise HTTPException(404, "Opportunity not found.")
    profile = get_active_profile(db)
    result = scoring.score_pipeline(opp.raw_text, profile_to_dict(profile))
    opp.parsed = result["parsed"]; opp.parse_confidence = result["parse_confidence"]
    model_used = "mock" if settings.mock_mode else f"{settings.fast_model}+{settings.strong_model}"
    db.add(Score(opportunity_id=opp.id, profile_version=profile.version,
                 overall_score=result["overall_score"], tier=result["tier"],
                 dimension_scores=result["dimension_scores"], hard_filter_result=result["hard_filter_result"],
                 confidence=result["parse_confidence"], memo_markdown=result["memo_markdown"],
                 model_used=model_used))
    db.commit()
    return _serialize_opp(db, opp)


# --------------------------------------------------------------------------
# Feedback / decision / outcome
# --------------------------------------------------------------------------
class FeedbackBody(BaseModel):
    override_score: Optional[float] = None
    override_tier: Optional[str] = None
    override_reason: str = ""


@router.post("/api/scores/{score_id}/feedback")
def add_feedback(score_id: str, body: FeedbackBody, db: Session = Depends(get_db),
                 user: User = Depends(require_user)):
    if not db.query(Score).filter(Score.id == score_id).first():
        raise HTTPException(404, "Score not found.")
    db.add(Feedback(score_id=score_id, user_id=user.id, override_score=body.override_score,
                    override_tier=body.override_tier or "", override_reason=body.override_reason))
    db.commit()
    return {"ok": True}


class DecisionBody(BaseModel):
    decision: str


@router.post("/api/opportunities/{opp_id}/decision")
def set_decision(opp_id: str, body: DecisionBody, db: Session = Depends(get_db),
                 user: User = Depends(require_user)):
    if body.decision not in ("pursue", "watch", "pass"):
        raise HTTPException(400, "decision must be pursue, watch, or pass.")
    db.add(Decision(opportunity_id=opp_id, user_id=user.id, decision=body.decision))
    db.commit()
    return {"ok": True}


class OutcomeBody(BaseModel):
    outcome: str
    amount: Optional[float] = None
    final_funding_type: str = ""
    notes: str = ""


@router.post("/api/opportunities/{opp_id}/outcome")
def set_outcome(opp_id: str, body: OutcomeBody, db: Session = Depends(get_db),
                user: User = Depends(require_user)):
    if body.outcome not in ("won", "lost", "declined", "withdrawn"):
        raise HTTPException(400, "outcome must be won, lost, declined, or withdrawn.")
    db.add(Outcome(opportunity_id=opp_id, outcome=body.outcome, amount=body.amount,
                   final_funding_type=body.final_funding_type, notes=body.notes))
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------
# Profile + setup/bootstrap (admin)
# --------------------------------------------------------------------------
@router.get("/api/profile/active")
def active_profile(db: Session = Depends(get_db), user: User = Depends(require_user)):
    return profile_to_dict(get_active_profile(db))


@router.get("/api/profiles")
def list_profiles(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    ps = db.query(StrategyProfile).order_by(desc(StrategyProfile.version)).all()
    return [{"version": p.version, "name": p.name, "is_active": p.is_active,
             "is_placeholder": p.is_placeholder, "created_at": p.created_at.isoformat()} for p in ps]


class ProfileBody(BaseModel):
    name: str = ""
    profile_doc: Dict[str, Any]
    dimensions: List[Dict[str, Any]]
    hard_filters: List[Dict[str, Any]]
    thresholds: Dict[str, Any]
    tiers: Dict[str, float]


@router.post("/api/profile")
def save_profile(body: ProfileBody, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    wsum = sum(d.get("weight", 0) for d in body.dimensions)
    if abs(wsum - 100) > 0.5:
        raise HTTPException(400, f"Dimension weights must sum to 100 (got {wsum}).")
    if not body.dimensions:
        raise HTTPException(400, "At least one dimension is required.")
    next_version = db.query(StrategyProfile).count() + 1
    db.query(StrategyProfile).update({StrategyProfile.is_active: False})
    db.add(StrategyProfile(
        version=next_version, name=body.name or f"Profile v{next_version}", profile_doc=body.profile_doc,
        dimensions=body.dimensions, hard_filters=body.hard_filters, thresholds=body.thresholds,
        tiers=body.tiers, is_active=True, is_placeholder=False, created_by=user.email, approved_by=user.email))
    db.commit()
    log(db, user.email, "profile_saved", {"version": next_version})
    return {"version": next_version}


class BootstrapBody(BaseModel):
    org_name: str
    org_description: str = ""
    plan_text: str = ""


@router.post("/api/setup/bootstrap")
def bootstrap(body: BootstrapBody, user: User = Depends(require_admin)):
    """Draft a profile from a strategic plan. Returns a draft; admin reviews and
    saves it via POST /api/profile. Does not persist on its own."""
    if len(body.plan_text) < 50 and len(body.org_description) < 50:
        raise HTTPException(400, "Provide an organization description and/or strategic plan text to draft from.")
    return claude_agents.bootstrap_profile(body.org_name, body.org_description, body.plan_text)


# --------------------------------------------------------------------------
# Recalibration (admin)
# --------------------------------------------------------------------------
def _gather_evidence(db: Session) -> Dict[str, Any]:
    rows = []
    for s in db.query(Score).order_by(desc(Score.created_at)).limit(300).all():
        fb = db.query(Feedback).filter(Feedback.score_id == s.id).first()
        oc = (db.query(Outcome).filter(Outcome.opportunity_id == s.opportunity_id)
              .order_by(desc(Outcome.resolved_at)).first())
        rows.append({"model_score": s.overall_score, "model_tier": s.tier,
                     "dimension_scores": {k: v.get("score") for k, v in (s.dimension_scores or {}).items()},
                     "override_tier": fb.override_tier if fb else None,
                     "override_reason": fb.override_reason if fb else None,
                     "outcome": oc.outcome if oc else None, "outcome_amount": oc.amount if oc else None})
    return {"records": rows, "n_records": len(rows), "n_outcomes": sum(1 for r in rows if r["outcome"])}


@router.post("/api/recalibration/run")
def run_recal(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    profile = get_active_profile(db)
    evidence = _gather_evidence(db)
    if evidence["n_outcomes"] < settings.recal_min_outcomes:
        return {"created": False,
                "message": f"Only {evidence['n_outcomes']} logged outcomes; {settings.recal_min_outcomes} required."}
    proposal = claude_agents.analyze_for_recalibration(profile_to_dict(profile), evidence)
    rec = Recalibration(from_profile_version=profile.version,
                        proposed_profile={"dimension_weights": proposal.get("proposed_dimension_weights", {}),
                                          "threshold_changes": proposal.get("proposed_threshold_changes", {}),
                                          "filter_changes": proposal.get("proposed_filter_changes", {})},
                        rationale=proposal.get("rationale", ""),
                        evidence={"expected_effect": proposal.get("expected_effect", ""),
                                  "confidence": proposal.get("confidence", "low"),
                                  "n_outcomes": evidence["n_outcomes"]},
                        status="pending")
    db.add(rec); db.commit()
    return {"created": True, "id": rec.id}


@router.get("/api/recalibration")
def list_recal(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    recs = db.query(Recalibration).order_by(desc(Recalibration.created_at)).all()
    return [{"id": r.id, "from_profile_version": r.from_profile_version, "proposed_profile": r.proposed_profile,
             "rationale": r.rationale, "evidence": r.evidence, "status": r.status,
             "created_at": r.created_at.isoformat()} for r in recs]


@router.post("/api/recalibration/{rec_id}/approve")
def approve_recal(rec_id: str, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    rec = db.query(Recalibration).filter(Recalibration.id == rec_id).first()
    if not rec or rec.status != "pending":
        raise HTTPException(404, "Pending recalibration not found.")
    base = get_active_profile(db)
    new_weights = rec.proposed_profile.get("dimension_weights") or {}
    dims = [dict(d) for d in base.dimensions]
    for d in dims:
        if d["key"] in new_weights:
            d["weight"] = new_weights[d["key"]]
    thresholds = {**base.thresholds, **(rec.proposed_profile.get("threshold_changes") or {})}
    next_version = db.query(StrategyProfile).count() + 1
    db.query(StrategyProfile).update({StrategyProfile.is_active: False})
    db.add(StrategyProfile(version=next_version, name=f"Profile v{next_version} (recalibrated)",
                           profile_doc=base.profile_doc, dimensions=dims, hard_filters=base.hard_filters,
                           thresholds=thresholds, tiers=base.tiers, is_active=True, is_placeholder=False,
                           created_by="recalibration", approved_by=user.email))
    rec.status = "approved"; rec.reviewed_by = user.email; rec.reviewed_at = datetime.utcnow()
    db.commit()
    return {"approved": True, "new_version": next_version}


@router.post("/api/recalibration/{rec_id}/reject")
def reject_recal(rec_id: str, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    rec = db.query(Recalibration).filter(Recalibration.id == rec_id).first()
    if not rec or rec.status != "pending":
        raise HTTPException(404, "Pending recalibration not found.")
    rec.status = "rejected"; rec.reviewed_by = user.email; rec.reviewed_at = datetime.utcnow()
    db.commit()
    return {"rejected": True}


# --------------------------------------------------------------------------
# Export (admin)
# --------------------------------------------------------------------------
@router.get("/api/export.csv")
def export_csv(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    buf = io.StringIO(); w = csv.writer(buf)
    w.writerow(["opportunity_id", "title", "funder", "amount", "funding_type", "overall_score",
                "tier", "profile_version", "decision", "outcome", "outcome_amount", "created_at"])
    for o in db.query(Opportunity).order_by(desc(Opportunity.created_at)).all():
        s = latest_score(db, o.id)
        d = (db.query(Decision).filter(Decision.opportunity_id == o.id)
             .order_by(desc(Decision.decided_at)).first())
        oc = (db.query(Outcome).filter(Outcome.opportunity_id == o.id)
              .order_by(desc(Outcome.resolved_at)).first())
        w.writerow([o.id, o.title, (o.parsed or {}).get("funder", ""), (o.parsed or {}).get("amount", ""),
                    (o.parsed or {}).get("funding_type", ""), s.overall_score if s else "",
                    s.tier if s else "", s.profile_version if s else "", d.decision if d else "",
                    oc.outcome if oc else "", oc.amount if oc else "", o.created_at.isoformat()])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=fit_scorer_export.csv"})
