# ruff: noqa: E501
"""Cover-letter orchestration, deterministic rendering, validation, and versioning."""

from __future__ import annotations

import copy
import json
import re
from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.ai import AIProviderError, sponsorship_claim
from app.cover_letter_ai import (
    PROMPT_VERSION,
    CompanyFact,
    CoverLetterProvider,
    verified_company_facts,
)
from app.cover_letter_schemas import (
    ClaimValidationIssue,
    CoverLetterContent,
    CoverLetterEditRequest,
    CoverLetterEvidence,
    CoverLetterGenerateRequest,
    CoverLetterParagraph,
    CoverLetterPlan,
    CoverLetterRead,
    CoverLetterValidation,
)
from app.cv_optimization_ai import OptimizationFact, approved_profile_facts
from app.cv_schemas import CvProfileDraft, CvValue
from app.discovery import prepare_application
from app.matching import extracted_skills
from app.models import (
    Application,
    CandidateProfile,
    CoverLetterStatus,
    DiscoveryMatchResult,
    GeneratedDocument,
    GeneratedDocumentStatus,
    Job,
    ProfileVersion,
    User,
)
from app.services import write_audit

DOCUMENT_TYPE = "COVER_LETTER"
LENGTH_LIMITS = {"SHORT": (180, 250), "STANDARD": (250, 400), "DETAILED": (400, 550)}
LANGUAGE_NAMES = {
    "en": {"en", "english", "inglês", "ingles", "inglés"},
    "es": {"es", "spanish", "español", "espanol", "castellano"},
    "pt": {"pt", "portuguese", "português", "portugues"},
}
COUNTRY_LANGUAGE = {"ES": "es", "PT": "pt"}
UNVERIFIED_COMPANY_PHRASES = (
    "culture of innovation",
    "commitment to sustainability",
    "market leadership",
    "market leader",
    "fast-growing team",
    "cultura de innovación",
    "compromiso con la sostenibilidad",
    "liderazgo de mercado",
    "equipo de rápido crecimiento",
    "cultura de inovação",
    "compromisso com a sustentabilidade",
    "liderança de mercado",
    "equipe em rápido crescimento",
)
SAFE_PROPER_WORDS = {
    "A",
    "An",
    "And",
    "At",
    "Dear",
    "From",
    "Hiring",
    "I",
    "In",
    "Manager",
    "My",
    "Sincerely",
    "The",
    "Thank",
    "This",
    "With",
    "Atenciosamente",
    "Caro",
    "Cara",
    "Estimado",
    "Estimada",
    "Gerente",
    "Gestor",
    "Prezada",
    "Prezado",
    "Saludos",
}
ParagraphKind = Literal[
    "OPENING",
    "MOTIVATION",
    "QUALIFICATIONS",
    "ACHIEVEMENT",
    "PROJECT",
    "AUTHORIZATION",
    "CLOSING",
]


def _text(value: CvValue) -> str:
    return "" if value.value is None else str(value.value).strip()


def latest_profile_version(db: Session, user_id: str) -> ProfileVersion:
    record = db.scalar(
        select(ProfileVersion)
        .where(ProfileVersion.user_id == user_id)
        .order_by(ProfileVersion.version.desc(), ProfileVersion.created_at.desc())
        .limit(1)
    )
    if not record:
        raise HTTPException(
            status_code=409,
            detail="Confirm a CV profile before generating a cover letter",
        )
    return record


def latest_match(db: Session, user_id: str, job_id: str) -> DiscoveryMatchResult:
    record = db.scalar(
        select(DiscoveryMatchResult)
        .where(DiscoveryMatchResult.user_id == user_id, DiscoveryMatchResult.job_id == job_id)
        .order_by(DiscoveryMatchResult.created_at.desc())
        .limit(1)
    )
    if not record:
        raise HTTPException(
            status_code=409,
            detail="A deterministic job recommendation is required before letter generation",
        )
    return record


def cover_letter_facts(profile: CvProfileDraft) -> list[OptimizationFact]:
    facts = approved_profile_facts(profile)

    def add(fact_id: str, section: str, value: str) -> None:
        if value and all(fact.id != fact_id for fact in facts):
            facts.append(OptimizationFact(fact_id, section, value))

    add("candidate:salary-expectation", "salary_expectation", _text(profile.salary_expectation))
    for index, value in enumerate(profile.preferred_locations):
        add(f"candidate:preferred-location:{index}", "preferred_locations", value.value)
    return facts


def resolve_language(requested: str | None, job: Job, profile: CandidateProfile) -> str:
    if requested:
        return requested
    normalized = (job.language or "").strip().casefold()
    for code, names in LANGUAGE_NAMES.items():
        if normalized in names:
            return code
    if (job.country or "").upper() in COUNTRY_LANGUAGE:
        return COUNTRY_LANGUAGE[(job.country or "").upper()]
    candidate_languages = {item.language.casefold() for item in profile.languages}
    for code in ("en", "es", "pt"):
        if candidate_languages & LANGUAGE_NAMES[code]:
            return code
    return "en"


def _generic_greeting(language: str, hiring_team: bool = False) -> str:
    if hiring_team:
        return {
            "en": "Dear Hiring Team,",
            "es": "Estimado equipo de selección:",
            "pt": "Prezada equipe de recrutamento,",
        }[language]
    return {
        "en": "Dear Hiring Manager,",
        "es": "Estimado responsable de contratación:",
        "pt": "Prezado gestor de contratação,",
    }[language]


def resolve_greeting(
    request: CoverLetterGenerateRequest, application: Application, language: str
) -> str:
    if request.hiring_manager_name:
        return {
            "en": f"Dear {request.hiring_manager_name},",
            "es": f"Estimado/a {request.hiring_manager_name}:",
            "pt": f"Prezado/a {request.hiring_manager_name},",
        }[language]
    if request.greeting_style == "HIRING_TEAM":
        return _generic_greeting(language, hiring_team=True)
    if request.greeting_style == "AUTO":
        for contact in application.recruiter_contacts:
            if isinstance(contact, dict) and contact.get("verified") is True:
                name = str(contact.get("name", "")).strip()
                if name:
                    return {
                        "en": f"Dear {name},",
                        "es": f"Estimado/a {name}:",
                        "pt": f"Prezado/a {name},",
                    }[language]
    return _generic_greeting(language)


def _localized(language: str) -> dict[str, str]:
    return {
        "en": {
            "opening": "The {title} opportunity at {company} stands out because it aligns with this documented part of my profile: {evidence}.",
            "motivation": "The position's stated focus on {requirements} makes it a relevant next application for my background.",
            "qualifications": "The verified qualifications most relevant to the role include {evidence}.",
            "achievement": "One directly relevant, documented example is: {evidence}.",
            "project": "A related project recorded in my profile is {evidence}.",
            "authorization": "For practical hiring considerations, my approved profile records {evidence}.",
            "closing": "I would welcome the opportunity to discuss how this evidence could support the priorities of the {title} role. Thank you for your consideration.",
            "signoff_professional": "Sincerely,",
            "signoff_warm": "With best regards,",
            "signoff_concise": "Regards,",
        },
        "es": {
            "opening": "La oportunidad de {title} en {company} destaca porque se alinea con esta parte documentada de mi perfil: {evidence}.",
            "motivation": "El enfoque indicado para el puesto en {requirements} hace que esta sea una candidatura relevante para mi trayectoria.",
            "qualifications": "Las cualificaciones verificadas más relevantes para el puesto incluyen {evidence}.",
            "achievement": "Un ejemplo documentado y directamente relevante es: {evidence}.",
            "project": "Un proyecto relacionado registrado en mi perfil es {evidence}.",
            "authorization": "Para los aspectos prácticos de contratación, mi perfil aprobado indica {evidence}.",
            "closing": "Agradecería la oportunidad de conversar sobre cómo estas evidencias pueden apoyar las prioridades del puesto de {title}. Gracias por su consideración.",
            "signoff_professional": "Atentamente,",
            "signoff_warm": "Reciba un cordial saludo,",
            "signoff_concise": "Saludos,",
        },
        "pt": {
            "opening": "A oportunidade de {title} na {company} se destaca por estar alinhada a esta parte documentada do meu perfil: {evidence}.",
            "motivation": "O foco indicado para a função em {requirements} torna esta uma candidatura relevante para a minha trajetória.",
            "qualifications": "As qualificações verificadas mais relevantes para a função incluem {evidence}.",
            "achievement": "Um exemplo documentado e diretamente relevante é: {evidence}.",
            "project": "Um projeto relacionado registrado no meu perfil é {evidence}.",
            "authorization": "Para os aspectos práticos da contratação, meu perfil aprovado registra {evidence}.",
            "closing": "Agradeço a oportunidade de conversar sobre como essas evidências podem apoiar as prioridades da função de {title}. Obrigado pela consideração.",
            "signoff_professional": "Atenciosamente,",
            "signoff_warm": "Com os melhores cumprimentos,",
            "signoff_concise": "Cumprimentos,",
        },
    }[language]


def _requirements(job: Job) -> str:
    values = [*job.requirements[:2], *job.preferred_qualifications[:1]]
    return ", ".join(values) if values else "the responsibilities described in the vacancy"


def _tone_sentence(tone: str, language: str) -> str:
    meanings = {
        "PROFESSIONAL": {
            "en": "The application is presented with a direct, professional focus.",
            "es": "La candidatura se presenta con un enfoque directo y profesional.",
            "pt": "A candidatura é apresentada com foco direto e profissional.",
        },
        "CONFIDENT": {
            "en": "The documented evidence provides a clear basis for a confident discussion of fit.",
            "es": "La evidencia documentada ofrece una base clara para conversar con confianza sobre el encaje.",
            "pt": "As evidências documentadas oferecem uma base clara para conversar com confiança sobre aderência.",
        },
        "CONCISE": {
            "en": "The strongest evidence is summarized here without repeating the full CV.",
            "es": "La evidencia principal se resume aquí sin repetir el CV completo.",
            "pt": "As evidências principais estão resumidas aqui sem repetir o currículo completo.",
        },
        "WARM": {
            "en": "I would value a constructive conversation about the role and its priorities.",
            "es": "Valoraré una conversación constructiva sobre el puesto y sus prioridades.",
            "pt": "Valorizarei uma conversa construtiva sobre a função e suas prioridades.",
        },
        "TECHNICAL": {
            "en": "The letter prioritizes the technical evidence most closely connected to the vacancy.",
            "es": "La carta prioriza la evidencia técnica más relacionada con la vacante.",
            "pt": "A carta prioriza as evidências técnicas mais relacionadas à vaga.",
        },
        "BUSINESS_ORIENTED": {
            "en": "The selected examples emphasize practical relevance to the role's stated outcomes.",
            "es": "Los ejemplos seleccionados destacan la relevancia práctica para los resultados indicados.",
            "pt": "Os exemplos selecionados destacam a relevância prática para os resultados indicados.",
        },
        "STARTUP_ORIENTED": {
            "en": "The application keeps the evidence focused, adaptable, and close to the work described.",
            "es": "La candidatura mantiene la evidencia enfocada, adaptable y próxima al trabajo descrito.",
            "pt": "A candidatura mantém as evidências focadas, adaptáveis e próximas ao trabalho descrito.",
        },
        "CORPORATE": {
            "en": "The application presents the evidence in a structured and role-specific manner.",
            "es": "La candidatura presenta la evidencia de forma estructurada y específica para el puesto.",
            "pt": "A candidatura apresenta as evidências de forma estruturada e específica para a função.",
        },
    }
    return meanings[tone][language]


def _filler_sentences(job: Job, language: str) -> list[str]:
    title = job.title or "the advertised role"
    company = job.company or "the hiring organization"
    location = ", ".join(filter(None, (job.city, job.country))) or "the stated location"
    workplace = job.workplace_type or "the stated workplace model"
    requirements = _requirements(job)
    templates = {
        "en": [
            f"The vacancy provides a concrete basis for discussing fit with the {title} responsibilities.",
            f"Its stated requirements—{requirements}—give that discussion a clear and role-specific focus.",
            f"I would be glad to explain how each cited example relates to the day-to-day priorities at {company}.",
            f"The {workplace} arrangement and {location} context can also be discussed directly during the hiring process.",
            "A focused interview would make it possible to clarify scope, immediate priorities, and measures of success.",
            "The evidence above is intentionally selective so that the letter complements rather than repeats the full CV.",
            "Each example has been chosen for its relevance to the vacancy instead of for general keyword coverage.",
            "That approach keeps the application centered on demonstrable experience and the role's stated needs.",
            "I would welcome questions about the context, responsibilities, and outcomes behind the cited work.",
            "The remaining details of the position can be evaluated against the same documented background in conversation.",
            "This application therefore focuses on evidence that can be discussed and verified during the selection process.",
            "The role offers a specific setting in which the documented experience above may be assessed on its merits.",
            "A conversation would also allow both sides to confirm expectations before moving further in the process.",
            "The letter avoids assumptions about the organization and concentrates on the vacancy information provided.",
            "That distinction keeps the motivation specific to the work while avoiding unsupported company claims.",
            "I am available to provide further context for the selected examples if it would assist the review.",
        ],
        "es": [
            f"La vacante ofrece una base concreta para conversar sobre el encaje con las responsabilidades de {title}.",
            f"Sus requisitos indicados —{requirements}— dan a esa conversación un enfoque claro y específico.",
            f"Estaré encantado de explicar cómo cada ejemplo se relaciona con las prioridades diarias en {company}.",
            f"La modalidad {workplace} y el contexto de {location} también pueden tratarse durante el proceso.",
            "Una entrevista permitiría aclarar el alcance, las prioridades inmediatas y las medidas de éxito.",
            "Las evidencias anteriores son selectivas para complementar, y no repetir, el CV completo.",
            "Cada ejemplo fue elegido por su relevancia para la vacante y no por una cobertura genérica de palabras clave.",
            "Este enfoque mantiene la candidatura centrada en experiencia demostrable y necesidades declaradas.",
            "Agradeceré preguntas sobre el contexto, las responsabilidades y los resultados del trabajo citado.",
            "Los demás detalles del puesto pueden contrastarse con la misma trayectoria documentada.",
            "La candidatura se centra así en evidencias verificables durante el proceso de selección.",
            "La función ofrece un contexto específico para valorar por sus méritos la experiencia indicada.",
            "Una conversación también permitiría confirmar expectativas antes de avanzar en el proceso.",
            "La carta evita suposiciones sobre la organización y se limita a la información disponible.",
            "Esa distinción mantiene la motivación específica sin introducir afirmaciones no verificadas.",
            "Puedo aportar más contexto sobre los ejemplos seleccionados si resulta útil para la revisión.",
        ],
        "pt": [
            f"A vaga oferece uma base concreta para conversar sobre a aderência às responsabilidades de {title}.",
            f"Os requisitos indicados —{requirements}— dão a essa conversa um foco claro e específico.",
            f"Terei satisfação em explicar como cada exemplo se relaciona às prioridades diárias na {company}.",
            f"O modelo {workplace} e o contexto de {location} também podem ser tratados durante o processo.",
            "Uma entrevista permitiria esclarecer escopo, prioridades imediatas e medidas de sucesso.",
            "As evidências acima são seletivas para complementar, e não repetir, o currículo completo.",
            "Cada exemplo foi escolhido pela relevância para a vaga, e não por cobertura genérica de palavras-chave.",
            "Essa abordagem mantém a candidatura centrada em experiência demonstrável e necessidades declaradas.",
            "Agradeço perguntas sobre o contexto, as responsabilidades e os resultados do trabalho citado.",
            "Os demais detalhes da função podem ser comparados com a mesma trajetória documentada.",
            "A candidatura se concentra, assim, em evidências verificáveis durante o processo seletivo.",
            "A função oferece um contexto específico para avaliar a experiência indicada por seus méritos.",
            "Uma conversa também permitiria confirmar expectativas antes de avançar no processo.",
            "A carta evita suposições sobre a organização e se limita às informações disponíveis.",
            "Essa distinção mantém a motivação específica sem introduzir afirmações não verificadas.",
            "Posso fornecer mais contexto sobre os exemplos selecionados se isso ajudar na avaliação.",
        ],
    }
    return templates[language]


def render_cover_letter(
    *,
    profile: CvProfileDraft,
    job: Job,
    application: Application,
    facts: list[OptimizationFact],
    company_facts: list[CompanyFact],
    plan: CoverLetterPlan,
    request: CoverLetterGenerateRequest,
    language: str,
) -> CoverLetterContent:
    facts_by_id = {fact.id: fact for fact in facts}
    company_by_id = {fact.id: fact for fact in company_facts}
    templates = _localized(language)
    company = (
        job.company.strip() if job.company and job.company.strip() else "the hiring organization"
    )
    title = job.title.strip() if job.title and job.title.strip() else "the advertised role"

    def evidence(ids: list[str], company_ids: list[str] | None = None) -> str:
        values = [facts_by_id[fact_id].text for fact_id in ids if fact_id in facts_by_id]
        values.extend(
            company_by_id[fact_id].text for fact_id in company_ids or [] if fact_id in company_by_id
        )
        return "; ".join(values)

    paragraphs: list[CoverLetterParagraph] = []

    def add(
        kind: ParagraphKind,
        text: str,
        candidate_ids: list[str] | None = None,
        company_ids: list[str] | None = None,
        confidence: float = 1,
    ) -> None:
        paragraphs.append(
            CoverLetterParagraph(
                kind=kind,
                text=text,
                baseline_text=text,
                candidate_fact_ids=candidate_ids or [],
                company_fact_ids=company_ids or [],
                confidence=confidence,
            )
        )

    opening_evidence = evidence(plan.opening_fact_ids, plan.company_fact_ids)
    add(
        "OPENING",
        templates["opening"].format(title=title, company=company, evidence=opening_evidence),
        plan.opening_fact_ids,
        plan.company_fact_ids,
    )
    add(
        "MOTIVATION",
        " ".join(
            (
                templates["motivation"].format(requirements=_requirements(job)),
                _tone_sentence(request.tone, language),
            )
        ),
        confidence=0.95,
    )
    add(
        "QUALIFICATIONS",
        templates["qualifications"].format(evidence=evidence(plan.qualification_fact_ids)),
        plan.qualification_fact_ids,
    )
    if plan.achievement_fact_ids:
        add(
            "ACHIEVEMENT",
            templates["achievement"].format(evidence=evidence(plan.achievement_fact_ids)),
            plan.achievement_fact_ids,
        )
    if plan.project_fact_ids:
        add(
            "PROJECT",
            templates["project"].format(evidence=evidence(plan.project_fact_ids)),
            plan.project_fact_ids,
        )
    if plan.authorization_fact_ids:
        add(
            "AUTHORIZATION",
            templates["authorization"].format(evidence=evidence(plan.authorization_fact_ids)),
            plan.authorization_fact_ids,
        )
    add("CLOSING", templates["closing"].format(title=title), confidence=1)
    minimum, maximum = LENGTH_LIMITS[request.length]
    filler = _filler_sentences(job, language)
    filler_index = 0
    while sum(len(item.text.split()) for item in paragraphs) < minimum:
        candidate = filler[filler_index % len(filler)]
        current = sum(len(item.text.split()) for item in paragraphs)
        if current + len(candidate.split()) > maximum:
            break
        if filler_index < len(filler):
            paragraphs[1].text += f" {candidate}"
            paragraphs[1].baseline_text += f" {candidate}"
        else:
            paragraphs[-1].text += f" {candidate}"
            paragraphs[-1].baseline_text += f" {candidate}"
        filler_index += 1
    contact_values = []
    if request.include_contact_details:
        contact_values = [
            _text(profile.personal.email),
            _text(profile.personal.phone),
            _text(profile.personal.city),
            _text(profile.personal.country),
        ]
    signoff = templates[f"signoff_{request.closing_style.casefold()}"]
    word_count = sum(len(item.text.split()) for item in paragraphs)
    return CoverLetterContent(
        candidate_name=_text(profile.personal.full_name) or "Candidate",
        contact_line=" | ".join(value for value in contact_values if value),
        date=datetime.now(UTC).date().isoformat(),
        company=company,
        job_title=title,
        greeting=resolve_greeting(request, application, language),
        paragraphs=paragraphs,
        signoff=signoff,
        word_count=word_count,
    )


def validate_cover_letter(
    content: CoverLetterContent,
    facts: list[OptimizationFact],
    company_facts: list[CompanyFact],
    configuration: dict,
) -> CoverLetterValidation:
    facts_by_id = {fact.id: fact for fact in facts}
    company_by_id = {fact.id: fact for fact in company_facts}
    issues: list[ClaimValidationIssue] = []
    low_confidence: list[int] = []
    all_evidence_text = " ".join(
        [*(fact.text for fact in facts), *(fact.text for fact in company_facts)]
    )
    allowed_proper = set(re.findall(r"\b[A-ZÀ-Ý][\w.+#-]*\b", all_evidence_text))
    allowed_proper.update(
        re.findall(
            r"\b[A-ZÀ-Ý][\w.+#-]*\b",
            f"{content.candidate_name} {content.company} {content.job_title}",
        )
    )
    for index, paragraph in enumerate(content.paragraphs):
        invalid_candidate_ids = [
            fact_id for fact_id in paragraph.candidate_fact_ids if fact_id not in facts_by_id
        ]
        invalid_company_ids = [
            fact_id for fact_id in paragraph.company_fact_ids if fact_id not in company_by_id
        ]
        if invalid_candidate_ids or invalid_company_ids:
            issues.append(
                ClaimValidationIssue(
                    code="INVALID_EVIDENCE_ID",
                    message="The paragraph cites evidence outside the approved catalogs.",
                    paragraph_index=index,
                    text=paragraph.text[:1000],
                )
            )
        cited_text = " ".join(
            [
                *(
                    facts_by_id[fact_id].text
                    for fact_id in paragraph.candidate_fact_ids
                    if fact_id in facts_by_id
                ),
                *(
                    company_by_id[fact_id].text
                    for fact_id in paragraph.company_fact_ids
                    if fact_id in company_by_id
                ),
            ]
        )
        cited_numbers = set(
            re.findall(
                r"\b\d+(?:[.,]\d+)?%?\b",
                f"{cited_text} {paragraph.baseline_text}",
            )
        )
        introduced_numbers = {
            number
            for number in re.findall(r"\b\d+(?:[.,]\d+)?%?\b", paragraph.text)
            if number not in cited_numbers
        }
        if introduced_numbers:
            issues.append(
                ClaimValidationIssue(
                    code="UNSUPPORTED_NUMBER",
                    message="A date, duration, or metric is not present in cited candidate evidence.",
                    paragraph_index=index,
                    text=", ".join(sorted(introduced_numbers)),
                )
            )
        cited_skills = extracted_skills([cited_text, paragraph.baseline_text])
        unsupported_skills = extracted_skills([paragraph.text]) - cited_skills
        if unsupported_skills:
            issues.append(
                ClaimValidationIssue(
                    code="UNSUPPORTED_SKILL",
                    message="The paragraph implies a skill not present in its cited evidence.",
                    paragraph_index=index,
                    text=", ".join(sorted(unsupported_skills)),
                )
            )
        normalized = paragraph.text.casefold()
        company_evidence_text = " ".join(
            company_by_id[fact_id].text.casefold()
            for fact_id in paragraph.company_fact_ids
            if fact_id in company_by_id
        )
        unsupported_company_phrase = next(
            (
                phrase
                for phrase in UNVERIFIED_COMPANY_PHRASES
                if phrase in normalized and phrase not in company_evidence_text
            ),
            None,
        )
        if unsupported_company_phrase:
            issues.append(
                ClaimValidationIssue(
                    code="UNSUPPORTED_COMPANY_CLAIM",
                    message="A company-specific statement has no verified company evidence.",
                    paragraph_index=index,
                    text=paragraph.text[:1000],
                )
            )
        if "salary" in normalized and not configuration.get("include_salary_expectations"):
            issues.append(
                ClaimValidationIssue(
                    code="SALARY_NOT_REQUESTED",
                    message="Salary expectations are excluded by this letter's configuration.",
                    paragraph_index=index,
                    text=paragraph.text[:1000],
                )
            )
        if re.search(r"\brelocat\w*\b", normalized) and not any(
            facts_by_id.get(fact_id) and facts_by_id[fact_id].section == "relocation"
            for fact_id in paragraph.candidate_fact_ids
        ):
            issues.append(
                ClaimValidationIssue(
                    code="UNSUPPORTED_RELOCATION",
                    message="Relocation wording is not supported by cited profile evidence.",
                    paragraph_index=index,
                    text=paragraph.text[:1000],
                )
            )
        sponsorship = sponsorship_claim(paragraph.text)
        if sponsorship is not None:
            sponsorship_fact = next(
                (
                    facts_by_id[fact_id].text.casefold()
                    for fact_id in paragraph.candidate_fact_ids
                    if fact_id == "candidate:requires-sponsorship" and fact_id in facts_by_id
                ),
                "",
            )
            expected = "requires sponsorship: true" in sponsorship_fact
            if not sponsorship_fact or sponsorship != expected:
                issues.append(
                    ClaimValidationIssue(
                        code="UNSUPPORTED_SPONSORSHIP",
                        message="Sponsorship wording contradicts approved profile evidence.",
                        paragraph_index=index,
                        text=paragraph.text[:1000],
                    )
                )
        if paragraph.text != paragraph.baseline_text:
            unknown_proper = {
                token
                for token in re.findall(r"\b[A-ZÀ-Ý][\w.+#-]*\b", paragraph.text)
                if token not in allowed_proper and token not in SAFE_PROPER_WORDS
            }
            if unknown_proper:
                issues.append(
                    ClaimValidationIssue(
                        code="UNSUPPORTED_PROPER_NOUN",
                        message="User-added names or entities are not present in approved evidence.",
                        paragraph_index=index,
                        text=", ".join(sorted(unknown_proper)),
                    )
                )
        if paragraph.confidence < 0.8:
            low_confidence.append(index)
    minimum, maximum = LENGTH_LIMITS[str(configuration.get("length", "STANDARD"))]
    if not minimum <= content.word_count <= maximum:
        issues.append(
            ClaimValidationIssue(
                code="LENGTH_OUT_OF_RANGE",
                message=f"Letter body must contain {minimum}-{maximum} words.",
                text=str(content.word_count),
            )
        )
    return CoverLetterValidation(
        valid=not issues,
        checked_claims=len(content.paragraphs),
        issues=issues,
        low_confidence_paragraphs=low_confidence,
    )


def _profile_hash(profile_version: ProfileVersion) -> str:
    encoded = json.dumps(profile_version.snapshot, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


def _job_hash(job: Job) -> str:
    return sha256(
        "\0".join(
            [
                job.title,
                job.company,
                job.description,
                *job.requirements,
                *job.preferred_qualifications,
            ]
        ).encode("utf-8")
    ).hexdigest()


def _next_version(db: Session, application_id: str) -> int:
    current = db.scalar(
        select(func.max(GeneratedDocument.version)).where(
            GeneratedDocument.application_id == application_id
        )
    )
    return (current or 0) + 1


def generate_cover_letters(
    db: Session,
    user: User,
    request: CoverLetterGenerateRequest,
    provider: CoverLetterProvider,
) -> list[GeneratedDocument]:
    job = db.get(Job, request.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    match = latest_match(db, user.id, job.id)
    profile_version = latest_profile_version(db, user.id)
    candidate_profile = db.scalar(
        select(CandidateProfile).where(CandidateProfile.user_id == user.id)
    )
    if not candidate_profile:
        raise HTTPException(status_code=409, detail="Candidate profile is required")
    application = prepare_application(db, user, match)
    profile = CvProfileDraft.model_validate(profile_version.snapshot)
    facts = cover_letter_facts(profile)
    company_facts = verified_company_facts(job)
    language = resolve_language(request.language, job, candidate_profile)
    request_with_language = request.model_copy(update={"language": language})
    input_state = {
        "job_hash": _job_hash(job),
        "profile_hash": _profile_hash(profile_version),
        "job_id": job.id,
        "profile_version_id": profile_version.id,
        "match_id": match.id,
        "application_id": application.id,
    }
    db.expunge(job)
    db.commit()
    try:
        plan_set, metadata = provider.select_plans(
            job=job,
            facts=facts,
            company_facts=company_facts,
            request=request_with_language,
            match_analysis=match.analysis,
        )
    except AIProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    current_job = db.get(Job, input_state["job_id"])
    current_profile_version = db.get(ProfileVersion, input_state["profile_version_id"])
    current_match = db.get(DiscoveryMatchResult, input_state["match_id"])
    current_application = db.get(Application, input_state["application_id"])
    if (
        not current_job
        or _job_hash(current_job) != input_state["job_hash"]
        or not current_profile_version
        or current_profile_version.user_id != user.id
        or _profile_hash(current_profile_version) != input_state["profile_hash"]
        or not current_match
        or current_match.user_id != user.id
        or not current_application
        or current_application.user_id != user.id
    ):
        raise HTTPException(status_code=409, detail="Cover-letter inputs changed; retry")
    application = current_application
    db.refresh(application, with_for_update=True)
    existing_selected = db.scalar(
        select(GeneratedDocument.id).where(
            GeneratedDocument.application_id == application.id,
            GeneratedDocument.document_type == DOCUMENT_TYPE,
            GeneratedDocument.selected.is_(True),
        )
    )
    records: list[GeneratedDocument] = []
    configuration = request_with_language.model_dump(mode="json")
    configuration.update(
        {
            "resolved_language": language,
            "missing_required_skills": current_match.analysis.get("missing_required_skills", []),
            "potential_blockers": current_match.analysis.get("potential_blockers", []),
            "reasons_to_apply": current_match.analysis.get("reasons_to_apply", []),
            "match_score": current_match.score,
        }
    )
    for plan in plan_set.plans:
        content = render_cover_letter(
            profile=profile,
            job=current_job,
            application=application,
            facts=facts,
            company_facts=company_facts,
            plan=plan,
            request=request_with_language,
            language=language,
        )
        validation = validate_cover_letter(content, facts, company_facts, configuration)
        record = GeneratedDocument(
            application_id=application.id,
            document_type=DOCUMENT_TYPE,
            job_id=current_job.id,
            profile_version_id=current_profile_version.id,
            version=_next_version(db, application.id),
            language=language,
            status=(
                GeneratedDocumentStatus.VALID
                if validation.valid
                else GeneratedDocumentStatus.INVALID
            ),
            content=content.model_dump(mode="json"),
            validation=validation.model_dump(mode="json"),
            prompt_version=PROMPT_VERSION,
            model=metadata.model,
            provider_response_id=metadata.provider_response_id,
            input_tokens=metadata.input_tokens,
            cached_input_tokens=metadata.cached_input_tokens,
            output_tokens=metadata.output_tokens,
            estimated_cost_usd=metadata.estimated_cost_usd,
            latency_ms=metadata.latency_ms,
            cover_letter_status=(
                CoverLetterStatus.VALIDATED if validation.valid else CoverLetterStatus.GENERATED
            ),
            variant=plan.variant,
            tone=request.tone,
            length=request.length,
            configuration_json=configuration,
            selected=existing_selected is None and not records,
        )
        db.add(record)
        db.flush()
        records.append(record)
        write_audit(
            db,
            user.id,
            "cover_letter.generated",
            "generated_document",
            record.id,
            {
                "variant": plan.variant,
                "language": language,
                "valid": validation.valid,
                "model": metadata.model,
                "latency_ms": metadata.latency_ms,
            },
        )
    return records


def owned_cover_letter(
    db: Session, user_id: str, document_id: str, lock: bool = False
) -> GeneratedDocument:
    statement = (
        select(GeneratedDocument)
        .join(Application)
        .where(
            GeneratedDocument.id == document_id,
            GeneratedDocument.document_type == DOCUMENT_TYPE,
            Application.user_id == user_id,
        )
    )
    if lock:
        statement = statement.with_for_update()
    record = db.scalar(statement)
    if not record:
        raise HTTPException(status_code=404, detail="Cover letter not found")
    return record


def _evidence_for(
    content: CoverLetterContent,
    facts: list[OptimizationFact],
    company_facts: list[CompanyFact],
) -> list[CoverLetterEvidence]:
    selected = {
        fact_id
        for paragraph in content.paragraphs
        for fact_id in [*paragraph.candidate_fact_ids, *paragraph.company_fact_ids]
    }
    evidence = [
        CoverLetterEvidence(fact_id=fact.id, source_section=fact.section, quote=fact.text)
        for fact in facts
        if fact.id in selected
    ]
    evidence.extend(
        CoverLetterEvidence(fact_id=fact.id, source_section=fact.source, quote=fact.text)
        for fact in company_facts
        if fact.id in selected
    )
    return evidence


def serialize_cover_letter(db: Session, record: GeneratedDocument) -> CoverLetterRead:
    if not record.profile_version_id or not record.job_id or not record.cover_letter_status:
        raise HTTPException(status_code=409, detail="Cover-letter metadata is incomplete")
    profile_version = db.get(ProfileVersion, record.profile_version_id)
    job = db.get(Job, record.job_id)
    if not profile_version or not job:
        raise HTTPException(status_code=409, detail="Cover-letter evidence is unavailable")
    profile = CvProfileDraft.model_validate(profile_version.snapshot)
    content = CoverLetterContent.model_validate(record.content)
    return CoverLetterRead(
        id=record.id,
        application_id=record.application_id,
        job_id=record.job_id,
        profile_version_id=record.profile_version_id,
        parent_document_id=record.parent_document_id,
        version=record.version,
        language=record.language,
        status=record.status,
        cover_letter_status=record.cover_letter_status,
        variant=record.variant or "BALANCED",
        tone=record.tone or "PROFESSIONAL",
        length=record.length or "STANDARD",
        selected=record.selected,
        content=content,
        validation=CoverLetterValidation.model_validate(record.validation),
        evidence=_evidence_for(content, cover_letter_facts(profile), verified_company_facts(job)),
        configuration=record.configuration_json,
        prompt_version=record.prompt_version,
        model=record.model,
        provider_response_id=record.provider_response_id,
        input_tokens=record.input_tokens,
        cached_input_tokens=record.cached_input_tokens,
        output_tokens=record.output_tokens,
        estimated_cost_usd=record.estimated_cost_usd,
        latency_ms=record.latency_ms,
        approved_at=record.approved_at,
        created_at=record.created_at,
    )


def edit_cover_letter(
    db: Session,
    user: User,
    document_id: str,
    payload: CoverLetterEditRequest,
) -> GeneratedDocument:
    parent = owned_cover_letter(db, user.id, document_id, lock=True)
    content = CoverLetterContent.model_validate(copy.deepcopy(parent.content))
    if len(payload.paragraphs) != len(content.paragraphs):
        raise HTTPException(
            status_code=422,
            detail="Edits must preserve the generated paragraph structure and evidence mapping",
        )
    content.greeting = payload.greeting
    content.signoff = payload.signoff
    for paragraph, text in zip(content.paragraphs, payload.paragraphs, strict=True):
        paragraph.text = text
    content.word_count = sum(len(item.text.split()) for item in content.paragraphs)
    profile_version = db.get(ProfileVersion, parent.profile_version_id)
    job = db.get(Job, parent.job_id)
    application = db.get(Application, parent.application_id)
    if not profile_version or not job or not application or application.user_id != user.id:
        raise HTTPException(status_code=409, detail="Cover-letter inputs are unavailable")
    facts = cover_letter_facts(CvProfileDraft.model_validate(profile_version.snapshot))
    validation = validate_cover_letter(
        content, facts, verified_company_facts(job), parent.configuration_json
    )
    db.refresh(application, with_for_update=True)
    db.execute(
        update(GeneratedDocument)
        .where(
            GeneratedDocument.application_id == application.id,
            GeneratedDocument.document_type == DOCUMENT_TYPE,
        )
        .values(selected=False)
    )
    record = GeneratedDocument(
        application_id=application.id,
        document_type=DOCUMENT_TYPE,
        job_id=parent.job_id,
        profile_version_id=parent.profile_version_id,
        parent_document_id=parent.id,
        version=_next_version(db, application.id),
        language=parent.language,
        status=(
            GeneratedDocumentStatus.VALID if validation.valid else GeneratedDocumentStatus.INVALID
        ),
        content=content.model_dump(mode="json"),
        validation=validation.model_dump(mode="json"),
        prompt_version=parent.prompt_version,
        model=parent.model,
        provider_response_id=None,
        input_tokens=None,
        cached_input_tokens=None,
        output_tokens=None,
        estimated_cost_usd=0,
        latency_ms=0,
        cover_letter_status=CoverLetterStatus.USER_EDITED,
        variant=parent.variant,
        tone=parent.tone,
        length=parent.length,
        configuration_json=parent.configuration_json,
        selected=True,
    )
    db.add(record)
    db.flush()
    write_audit(
        db,
        user.id,
        "cover_letter.edited",
        "generated_document",
        record.id,
        {"parent_document_id": parent.id, "valid": validation.valid},
    )
    return record


def revalidate_cover_letter(db: Session, user: User, document_id: str) -> GeneratedDocument:
    record = owned_cover_letter(db, user.id, document_id, lock=True)
    profile_version = db.get(ProfileVersion, record.profile_version_id)
    job = db.get(Job, record.job_id)
    if not profile_version or not job:
        raise HTTPException(status_code=409, detail="Cover-letter evidence is unavailable")
    validation = validate_cover_letter(
        CoverLetterContent.model_validate(record.content),
        cover_letter_facts(CvProfileDraft.model_validate(profile_version.snapshot)),
        verified_company_facts(job),
        record.configuration_json,
    )
    record.validation = validation.model_dump(mode="json")
    record.status = (
        GeneratedDocumentStatus.VALID if validation.valid else GeneratedDocumentStatus.INVALID
    )
    if validation.valid and record.cover_letter_status not in {
        CoverLetterStatus.APPROVED,
        CoverLetterStatus.EXPORTED,
    }:
        record.cover_letter_status = CoverLetterStatus.VALIDATED
    write_audit(
        db,
        user.id,
        "cover_letter.validated",
        "generated_document",
        record.id,
        {"valid": validation.valid, "issues": len(validation.issues)},
    )
    return record


def select_cover_letter(db: Session, user: User, document_id: str) -> GeneratedDocument:
    record = owned_cover_letter(db, user.id, document_id, lock=True)
    db.execute(
        update(GeneratedDocument)
        .where(
            GeneratedDocument.application_id == record.application_id,
            GeneratedDocument.document_type == DOCUMENT_TYPE,
        )
        .values(selected=False)
    )
    record.selected = True
    write_audit(db, user.id, "cover_letter.selected", "generated_document", record.id)
    return record


def approve_cover_letter(db: Session, user: User, document_id: str) -> GeneratedDocument:
    record = revalidate_cover_letter(db, user, document_id)
    validation = CoverLetterValidation.model_validate(record.validation)
    if not validation.valid or record.status != GeneratedDocumentStatus.VALID:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Unsupported claims must be resolved before approval",
        )
    select_cover_letter(db, user, record.id)
    record.cover_letter_status = CoverLetterStatus.APPROVED
    record.approved_at = datetime.now(UTC)
    record.approved_by = user.id
    write_audit(db, user.id, "cover_letter.approved", "generated_document", record.id)
    return record


def request_from_configuration(record: GeneratedDocument) -> CoverLetterGenerateRequest:
    allowed = CoverLetterGenerateRequest.model_fields
    values = {key: value for key, value in record.configuration_json.items() if key in allowed}
    values["job_id"] = record.job_id
    values["variants"] = [record.variant or "BALANCED"]
    return CoverLetterGenerateRequest.model_validate(values)
