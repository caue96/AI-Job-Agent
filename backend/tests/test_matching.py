from types import SimpleNamespace

from app.matching import MatchingPolicy, location_score, score_job


def policy(**overrides) -> MatchingPolicy:
    defaults = {
        "permitted_countries": {"PT", "ES", "IE"},
        "allow_remote": True,
        "hard_reject_missing_required_skills": True,
        "hard_reject_missing_language": True,
        "hard_reject_salary_below_min": True,
        "hard_reject_outside_location": True,
        "hard_reject_seniority_gap": True,
        "hard_reject_incompatible_work_authorization": True,
        "seniority_gap_years": 2,
    }
    return MatchingPolicy(**(defaults | overrides))


def profile(**overrides):
    defaults = {
        "preferred_titles": ["Data Analyst", "Power BI Developer"],
        "preferred_locations": ["Porto", "Portugal"],
        "preferred_industries": ["Logistics"],
        "workplace_preferences": ["HYBRID", "REMOTE"],
        "relocation_available": False,
        "eu_work_authorized": True,
        "min_salary": 40000,
        "total_years_experience": 8,
        "skills": [
            SimpleNamespace(name="Python", years_experience=8),
            SimpleNamespace(name="SQL", years_experience=8),
            SimpleNamespace(name="Power BI", years_experience=6),
        ],
        "languages": [
            SimpleNamespace(language="Portuguese", proficiency="native"),
            SimpleNamespace(language="English", proficiency="advanced"),
            SimpleNamespace(language="Spanish", proficiency="intermediate"),
        ],
    }
    return SimpleNamespace(**(defaults | overrides))


def job(**overrides):
    defaults = {
        "title": "Data Analyst",
        "requirements": ["5 years of Python and SQL", "English"],
        "preferred_qualifications": ["Power BI"],
        "country": "PT",
        "city": "Porto",
        "workplace_type": "HYBRID",
        "language": "English",
        "sponsorship_information": "No sponsorship. Right to work required.",
        "salary_max": 50000,
        "industry": "Logistics",
    }
    return SimpleNamespace(**(defaults | overrides))


def test_deterministic_match_is_fully_explainable():
    analysis = score_job(profile(), job(), policy())

    assert analysis.overall_score == 100
    assert analysis.recommendation == "STRONG_MATCH"
    assert analysis.hard_rejected is False
    assert analysis.matching_skills == ["power bi", "python", "sql"]
    assert analysis.score_by_category["required_technical_skills"].score == 25
    assert analysis.missing_required_skills == []


def test_configurable_hard_rejection_rules_report_blockers():
    analysis = score_job(
        profile(),
        job(
            requirements=["12 years of JavaScript", "Fluent German"],
            preferred_qualifications=[],
            country="DE",
            city="Berlin",
            workplace_type="ON_SITE",
            language="German",
            salary_max=30000,
            industry="Finance",
        ),
        policy(),
    )

    assert analysis.recommendation == "REJECT"
    assert analysis.hard_rejected is True
    assert analysis.missing_required_skills == ["javascript"]
    assert any("Missing required skills" in blocker for blocker in analysis.potential_blockers)
    assert any("Missing required languages" in blocker for blocker in analysis.potential_blockers)
    assert any("salary is below" in blocker.lower() for blocker in analysis.potential_blockers)
    assert any("seniority" in blocker.lower() for blocker in analysis.potential_blockers)


def test_remote_relocation_and_policy_location_paths():
    remote_score, remote_blocker = location_score(
        profile(preferred_locations=[], workplace_preferences=["REMOTE"]),
        job(country="US", city="New York", workplace_type="REMOTE"),
        policy(allow_remote=True),
    )
    relocation_score, relocation_blocker = location_score(
        profile(preferred_locations=[], relocation_available=True),
        job(country="ES", city="Madrid", workplace_type="ON_SITE"),
        policy(),
    )
    blocked_score, blocked_reason = location_score(
        profile(preferred_locations=[]),
        job(country="US", city="New York", workplace_type="REMOTE"),
        policy(allow_remote=False),
    )

    assert (remote_score.score, remote_blocker) == (10, None)
    assert (relocation_score.score, relocation_blocker) == (6, None)
    assert blocked_score.score == 0
    assert blocked_reason == "Remote work is disabled by matching policy."


def test_partial_experience_and_optional_data_paths():
    analysis = score_job(
        profile(
            total_years_experience=4,
            skills=[SimpleNamespace(name="Python", years_experience=4)],
            preferred_locations=[],
            workplace_preferences=["REMOTE"],
            preferred_industries=[],
            min_salary=None,
        ),
        job(
            requirements=["5 years of Python"],
            preferred_qualifications=["JavaScript"],
            country="US",
            city=None,
            workplace_type="REMOTE",
            language=None,
            sponsorship_information="",
            salary_max=None,
            industry=None,
        ),
        policy(allow_remote=True, hard_reject_missing_required_skills=False),
    )

    assert analysis.score_by_category["experience_level"].score == 6
    assert analysis.score_by_category["location_and_remote"].score == 10
    assert (
        analysis.score_by_category["salary"].explanation
        == "Salary is not available for comparison."
    )
    assert analysis.missing_preferred_skills == ["javascript"]


def test_incompatible_authorization_can_be_a_hard_blocker():
    analysis = score_job(
        profile(eu_work_authorized=False),
        job(country="DE", sponsorship_information="Right to work required."),
        policy(),
    )

    assert analysis.score_by_category["eu_work_authorization"].score == 0
    assert analysis.recommendation == "REJECT"
    assert any("authorization" in blocker for blocker in analysis.potential_blockers)


def test_title_matching_preserves_non_ascii_words():
    analysis = score_job(
        profile(preferred_titles=["数据分析师"]),
        job(title="数据分析师"),
        policy(),
    )

    assert analysis.score_by_category["job_title"].score > 0
