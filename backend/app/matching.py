"""Deterministic, explainable job matching with no model-generated facts."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.config import Settings
from app.models import CandidateProfile, Job
from app.schemas import MatchAnalysisRead, ScoreCategory

EU_COUNTRIES = {
    "AT",
    "BE",
    "BG",
    "HR",
    "CY",
    "CZ",
    "DK",
    "EE",
    "FI",
    "FR",
    "DE",
    "GR",
    "HU",
    "IE",
    "IT",
    "LV",
    "LT",
    "LU",
    "MT",
    "NL",
    "PL",
    "PT",
    "RO",
    "SK",
    "SI",
    "ES",
    "SE",
}

SKILL_ALIASES = {
    "python": {"python"},
    "sql": {"sql"},
    "power bi": {"power bi", "powerbi"},
    "dax": {"dax"},
    "power apps": {"power apps", "powerapps"},
    "power fx": {"power fx", "powerfx"},
    "power automate": {"power automate", "powerautomate"},
    "excel": {"excel", "microsoft excel"},
    "vba": {"vba", "visual basic for applications"},
    "javascript": {"javascript", "ecmascript"},
    "sharepoint": {"sharepoint"},
    "rest api": {"rest api", "restful api", "restful services"},
}

LANGUAGE_ALIASES = {
    "portuguese": {"portuguese", "português"},
    "english": {"english", "inglês"},
    "spanish": {"spanish", "español", "espanhol"},
    "french": {"french", "français", "frances"},
    "german": {"german", "deutsch", "alemão"},
    "italian": {"italian", "italiano"},
}

COUNTRY_NAMES = {
    "ES": {"es", "spain", "españa", "espanha"},
    "PT": {"pt", "portugal"},
    "IE": {"ie", "ireland", "irlanda"},
}


@dataclass(frozen=True)
class MatchingPolicy:
    permitted_countries: set[str]
    allow_remote: bool
    hard_reject_missing_required_skills: bool
    hard_reject_missing_language: bool
    hard_reject_salary_below_min: bool
    hard_reject_outside_location: bool
    hard_reject_seniority_gap: bool
    hard_reject_incompatible_work_authorization: bool
    seniority_gap_years: float

    @classmethod
    def from_settings(cls, settings: Settings) -> MatchingPolicy:
        return cls(
            permitted_countries=settings.permitted_countries,
            allow_remote=settings.matching_allow_remote,
            hard_reject_missing_required_skills=settings.matching_hard_reject_missing_required_skills,
            hard_reject_missing_language=settings.matching_hard_reject_missing_language,
            hard_reject_salary_below_min=settings.matching_hard_reject_salary_below_min,
            hard_reject_outside_location=settings.matching_hard_reject_outside_location,
            hard_reject_seniority_gap=settings.matching_hard_reject_seniority_gap,
            hard_reject_incompatible_work_authorization=(
                settings.matching_hard_reject_incompatible_work_authorization
            ),
            seniority_gap_years=settings.matching_seniority_gap_years,
        )


def normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())


def contains_alias(text: str, aliases: set[str]) -> bool:
    return any(re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", text) for alias in aliases)


def extracted_skills(items: list[str]) -> set[str]:
    text = normalized(" ".join(items))
    return {skill for skill, aliases in SKILL_ALIASES.items() if contains_alias(text, aliases)}


def canonical_profile_skills(profile: CandidateProfile) -> set[str]:
    result: set[str] = set()
    for profile_skill in profile.skills:
        name = normalized(profile_skill.name)
        for canonical, aliases in SKILL_ALIASES.items():
            if name == canonical or name in aliases:
                result.add(canonical)
    return result


def extracted_languages(items: list[str]) -> set[str]:
    text = normalized(" ".join(items))
    return {
        language for language, aliases in LANGUAGE_ALIASES.items() if contains_alias(text, aliases)
    }


def canonical_profile_languages(profile: CandidateProfile) -> set[str]:
    result: set[str] = set()
    for profile_language in profile.languages:
        name = normalized(profile_language.language)
        for canonical, aliases in LANGUAGE_ALIASES.items():
            if name == canonical or name in aliases:
                result.add(canonical)
    return result


def score_fraction(matches: int, total: int, maximum: int) -> int:
    return maximum if total == 0 else round(maximum * matches / total)


def candidate_experience(profile: CandidateProfile) -> float:
    declared = profile.total_years_experience or 0
    skill_years = [skill.years_experience or 0 for skill in profile.skills]
    return max(declared, max(skill_years, default=0))


def required_years(job: Job) -> float | None:
    matches = re.findall(
        r"\b(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)\b", normalized(" ".join(job.requirements))
    )
    return max((float(value) for value in matches), default=None)


def title_score(profile: CandidateProfile, job: Job) -> ScoreCategory:
    word_pattern = r"[^\W\d_]+"
    target = set(re.findall(word_pattern, normalized(job.title)))
    candidates = [
        set(re.findall(word_pattern, normalized(title))) for title in profile.preferred_titles
    ]
    overlap = max(
        (len(target & candidate) / max(len(target), 1) for candidate in candidates), default=0
    )
    score = round(15 * overlap)
    explanation = "No preferred titles are configured."
    if overlap:
        explanation = f"Title token overlap with preferred roles: {round(overlap * 100)}%."
    return ScoreCategory(score=score, maximum=15, explanation=explanation)


def location_score(
    profile: CandidateProfile, job: Job, policy: MatchingPolicy
) -> tuple[ScoreCategory, str | None]:
    workplace = normalized(job.workplace_type or "")
    is_remote = "remote" in workplace
    preferences = {normalized(value) for value in profile.workplace_preferences}
    locations = {normalized(value) for value in profile.preferred_locations}
    country_terms = COUNTRY_NAMES.get(job.country or "", {normalized(job.country or "")})
    location_match = bool(locations & country_terms) or (
        job.city is not None and normalized(job.city) in locations
    )
    if is_remote and policy.allow_remote and (not preferences or "remote" in preferences):
        return ScoreCategory(
            score=10, maximum=10, explanation="Remote work matches the profile preference."
        ), None
    if location_match:
        return ScoreCategory(
            score=10, maximum=10, explanation="Country or city matches a preferred location."
        ), None
    if profile.relocation_available and (
        not job.country or job.country in policy.permitted_countries
    ):
        return ScoreCategory(
            score=6, maximum=10, explanation="Relocation is available within permitted countries."
        ), None
    if is_remote and not policy.allow_remote:
        blocker = "Remote work is disabled by matching policy."
    else:
        blocker = "Job location is outside configured preferences and relocation scope."
    return ScoreCategory(score=0, maximum=10, explanation=blocker), blocker


def score_job(profile: CandidateProfile, job: Job, policy: MatchingPolicy) -> MatchAnalysisRead:
    profile_skills = canonical_profile_skills(profile)
    required_skills = extracted_skills(job.requirements)
    preferred_skills = extracted_skills(job.preferred_qualifications)
    matching_skills = sorted(profile_skills & (required_skills | preferred_skills))
    missing_required = sorted(required_skills - profile_skills)
    missing_preferred = sorted(preferred_skills - profile_skills)
    blockers: list[str] = []
    reasons_to_apply: list[str] = []
    reasons_not_to_apply: list[str] = []

    categories: dict[str, ScoreCategory] = {"job_title": title_score(profile, job)}
    categories["required_technical_skills"] = ScoreCategory(
        score=score_fraction(len(required_skills & profile_skills), len(required_skills), 25),
        maximum=25,
        explanation=(
            "No recognized technical requirements were supplied."
            if not required_skills
            else (
                f"{len(required_skills & profile_skills)} of {len(required_skills)} "
                "required skills match."
            )
        ),
    )
    categories["preferred_skills"] = ScoreCategory(
        score=score_fraction(len(preferred_skills & profile_skills), len(preferred_skills), 10),
        maximum=10,
        explanation=(
            "No recognized preferred technical skills were supplied."
            if not preferred_skills
            else (
                f"{len(preferred_skills & profile_skills)} of {len(preferred_skills)} "
                "preferred skills match."
            )
        ),
    )
    if missing_required:
        detail = f"Missing required skills: {', '.join(missing_required)}."
        reasons_not_to_apply.append(detail)
        if policy.hard_reject_missing_required_skills:
            blockers.append(detail)
    if missing_preferred:
        reasons_not_to_apply.append(f"Missing preferred skills: {', '.join(missing_preferred)}.")

    experience = candidate_experience(profile)
    required_experience = required_years(job)
    if required_experience is None:
        categories["experience_level"] = ScoreCategory(
            score=10, maximum=10, explanation="No numeric experience requirement found."
        )
    elif experience >= required_experience:
        categories["experience_level"] = ScoreCategory(
            score=10, maximum=10, explanation="Declared experience meets the numeric requirement."
        )
    elif experience + 1 >= required_experience:
        categories["experience_level"] = ScoreCategory(
            score=6,
            maximum=10,
            explanation="Declared experience is within one year of the requirement.",
        )
    else:
        categories["experience_level"] = ScoreCategory(
            score=0,
            maximum=10,
            explanation="Declared experience is below the numeric requirement.",
        )
        reasons_not_to_apply.append("Declared experience is below the stated requirement.")
        if (
            policy.hard_reject_seniority_gap
            and required_experience > experience + policy.seniority_gap_years
        ):
            blockers.append("Required seniority substantially exceeds declared experience.")

    categories["location_and_remote"], location_blocker = location_score(profile, job, policy)
    if location_blocker:
        if policy.hard_reject_outside_location:
            blockers.append(location_blocker)
        reasons_not_to_apply.append(location_blocker)

    language_requirements = extracted_languages(job.requirements)
    if job.language:
        language_requirements |= extracted_languages([job.language])
    profile_languages = canonical_profile_languages(profile)
    missing_languages = sorted(language_requirements - profile_languages)
    categories["language"] = ScoreCategory(
        score=score_fraction(
            len(language_requirements & profile_languages), len(language_requirements), 10
        ),
        maximum=10,
        explanation=(
            "No language requirement was supplied."
            if not language_requirements
            else (
                f"{len(language_requirements & profile_languages)} of "
                f"{len(language_requirements)} languages match."
            )
        ),
    )
    if missing_languages:
        detail = f"Missing required languages: {', '.join(missing_languages)}."
        reasons_not_to_apply.append(detail)
        if policy.hard_reject_missing_language:
            blockers.append(detail)

    sponsorship_text = normalized(job.sponsorship_information or "")
    authorization_required = any(
        phrase in sponsorship_text
        for phrase in ("no sponsorship", "right to work", "work authorization", "eligible to work")
    )
    eu_compatible = job.country in EU_COUNTRIES and profile.eu_work_authorized
    if eu_compatible or not authorization_required:
        categories["eu_work_authorization"] = ScoreCategory(
            score=10,
            maximum=10,
            explanation="Declared EU work authorization is compatible with the vacancy.",
        )
    else:
        categories["eu_work_authorization"] = ScoreCategory(
            score=0,
            maximum=10,
            explanation="Work-authorization compatibility cannot be established.",
        )
        blocker = "The vacancy requires work authorization that the profile does not establish."
        if policy.hard_reject_incompatible_work_authorization:
            blockers.append(blocker)
        reasons_not_to_apply.append(blocker)

    if profile.min_salary is None or job.salary_max is None:
        salary_known = False
        salary_matches = True
    else:
        salary_known = True
        salary_matches = job.salary_max >= profile.min_salary
    categories["salary"] = ScoreCategory(
        score=5 if salary_matches else 0,
        maximum=5,
        explanation=(
            "Salary is not available for comparison."
            if not salary_known
            else "Advertised maximum meets the configured minimum."
            if salary_matches
            else "Advertised maximum is below the configured minimum."
        ),
    )
    if not salary_matches:
        detail = "Advertised salary is below the configured minimum."
        reasons_not_to_apply.append(detail)
        if policy.hard_reject_salary_below_min:
            blockers.append(detail)

    industries = {normalized(value) for value in profile.preferred_industries}
    industry_match = (
        job.industry is None or not industries or normalized(job.industry) in industries
    )
    categories["industry_preference"] = ScoreCategory(
        score=5 if industry_match else 0,
        maximum=5,
        explanation=(
            "Industry is not constrained by the profile."
            if job.industry is None or not industries
            else "Job industry matches a preferred industry."
            if industry_match
            else "Job industry is outside preferred industries."
        ),
    )
    if not industry_match:
        reasons_not_to_apply.append("Job industry is outside preferred industries.")

    for category, score_detail in categories.items():
        if score_detail.score == score_detail.maximum and category not in {
            "salary",
            "industry_preference",
        }:
            reasons_to_apply.append(score_detail.explanation)
    if matching_skills:
        reasons_to_apply.append(f"Matching skills: {', '.join(matching_skills)}.")

    overall = sum(category.score for category in categories.values())
    hard_rejected = bool(blockers)
    recommendation = (
        "REJECT"
        if hard_rejected
        else "STRONG_MATCH"
        if overall >= 75
        else "POSSIBLE_MATCH"
        if overall >= 50
        else "WEAK_MATCH"
    )
    confidence = (
        "HIGH"
        if required_skills and job.country and job.workplace_type
        else "MEDIUM"
        if required_skills
        else "LOW"
    )
    return MatchAnalysisRead(
        overall_score=overall,
        score_by_category=categories,
        matching_skills=matching_skills,
        missing_required_skills=missing_required,
        missing_preferred_skills=missing_preferred,
        potential_blockers=list(dict.fromkeys(blockers)),
        reasons_to_apply=list(dict.fromkeys(reasons_to_apply)),
        reasons_not_to_apply=list(dict.fromkeys(reasons_not_to_apply)),
        confidence_level=confidence,
        recommendation=recommendation,
        hard_rejected=hard_rejected,
    )
