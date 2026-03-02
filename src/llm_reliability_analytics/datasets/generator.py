"""Structured synthetic dataset generator for LLM evaluation demos."""

import json
from pathlib import Path

import duckdb
import pandas as pd
from pydantic import BaseModel, Field

from llm_reliability_analytics.models.domain import DifficultyLevel, TestCase, TestSource

DEFAULT_CATEGORIES: tuple[str, ...] = (
    "factual_qa",
    "classification",
    "information_extraction",
    "numeric_reasoning",
    "format_constrained_json",
    "instruction_following",
    "consistency_check",
)


class DatasetGenerationConfig(BaseModel):
    total_cases: int = 300
    dataset_version: str = "v2.0-demo"
    output_jsonl: Path = Path("data/raw/llm_eval_dataset_v2_300.jsonl")
    output_parquet: Path = Path("data/raw/llm_eval_dataset_v2_300.parquet")


FACTUAL_QA_ITEMS: tuple[tuple[str, str], ...] = (
    ("Japan", "Tokyo"),
    ("France", "Paris"),
    ("Germany", "Berlin"),
    ("Canada", "Ottawa"),
    ("Italy", "Rome"),
    ("Spain", "Madrid"),
    ("Portugal", "Lisbon"),
    ("Netherlands", "Amsterdam"),
    ("Belgium", "Brussels"),
    ("Switzerland", "Bern"),
    ("Austria", "Vienna"),
    ("Poland", "Warsaw"),
    ("Czech Republic", "Prague"),
    ("Hungary", "Budapest"),
    ("Greece", "Athens"),
    ("Turkey", "Ankara"),
    ("Norway", "Oslo"),
    ("Sweden", "Stockholm"),
    ("Finland", "Helsinki"),
    ("Denmark", "Copenhagen"),
    ("Ireland", "Dublin"),
    ("Iceland", "Reykjavik"),
    ("Ukraine", "Kyiv"),
    ("Romania", "Bucharest"),
    ("Bulgaria", "Sofia"),
    ("Serbia", "Belgrade"),
    ("Croatia", "Zagreb"),
    ("Slovakia", "Bratislava"),
    ("Slovenia", "Ljubljana"),
    ("Estonia", "Tallinn"),
    ("Latvia", "Riga"),
    ("Lithuania", "Vilnius"),
    ("Morocco", "Rabat"),
    ("Egypt", "Cairo"),
    ("Algeria", "Algiers"),
    ("Tunisia", "Tunis"),
    ("Kenya", "Nairobi"),
    ("Ethiopia", "Addis Ababa"),
    ("South Africa", "Pretoria"),
    ("Nigeria", "Abuja"),
    ("Brazil", "Brasilia"),
    ("Argentina", "Buenos Aires"),
    ("Chile", "Santiago"),
    ("Peru", "Lima"),
    ("Mexico", "Mexico City"),
    ("United States", "Washington"),
    ("Australia", "Canberra"),
    ("New Zealand", "Wellington"),
    ("India", "New Delhi"),
    ("Kazakhstan", "Astana"),
    ("Uzbekistan", "Tashkent"),
    ("South Korea", "Seoul"),
)

FACTUAL_QA_TEMPLATES: tuple[str, ...] = (
    "Factual QA task: output ONLY the capital city name for {country}. No extra words.",
    "Return only the capital of {country}. Single city name only.",
    "Question: What is the capital of {country}? Answer with one city word/phrase only.",
)

POSITIVE_SUBJECTS: tuple[str, ...] = (
    "battery life",
    "camera quality",
    "screen clarity",
    "customer support",
    "delivery speed",
    "installation process",
    "audio quality",
    "keyboard feel",
    "documentation quality",
    "app stability",
    "navigation speed",
    "build quality",
    "search relevance",
    "checkout flow",
    "voice recognition",
    "response speed",
)

NEGATIVE_SUBJECTS: tuple[str, ...] = (
    "battery life",
    "camera quality",
    "screen clarity",
    "customer support",
    "delivery speed",
    "installation process",
    "audio quality",
    "keyboard feel",
    "documentation quality",
    "app stability",
    "navigation speed",
    "build quality",
    "search relevance",
    "checkout flow",
    "voice recognition",
    "response speed",
)

NEUTRAL_SUBJECTS: tuple[str, ...] = (
    "battery life",
    "camera quality",
    "screen clarity",
    "customer support",
    "delivery speed",
    "installation process",
    "audio quality",
    "keyboard feel",
    "documentation quality",
    "app stability",
    "navigation speed",
    "build quality",
    "search relevance",
    "checkout flow",
    "voice recognition",
    "response speed",
)

POSITIVE_ADJECTIVES: tuple[str, ...] = ("excellent", "great", "reliable", "smooth", "impressive")
NEGATIVE_ADJECTIVES: tuple[str, ...] = ("poor", "slow", "frustrating", "unstable", "disappointing")
NEUTRAL_ADJECTIVES: tuple[str, ...] = ("average", "acceptable", "ordinary", "standard", "typical")

CLASSIFICATION_TEMPLATES: tuple[str, ...] = (
    "Classification task: output EXACTLY one label from [positive, negative, neutral] for text: '{text}'",
    "Sentiment labeling: return only positive, negative, or neutral for: '{text}'",
    "Assign one sentiment label [positive|negative|neutral] to this review: '{text}'. Output label only.",
)

FIRST_NAMES: tuple[str, ...] = (
    "alex",
    "maria",
    "john",
    "lina",
    "david",
    "sofia",
    "omar",
    "sara",
    "liam",
    "emma",
    "oliver",
    "mia",
    "daniel",
    "nora",
    "noah",
    "anna",
    "mark",
    "elena",
    "yusuf",
    "ayana",
)

LAST_NAMES: tuple[str, ...] = (
    "smith",
    "johnson",
    "williams",
    "brown",
    "jones",
    "garcia",
    "miller",
    "davis",
    "wilson",
    "anderson",
    "thomas",
    "taylor",
    "moore",
    "martin",
    "lee",
)

EMAIL_DOMAINS: tuple[str, ...] = (
    "example.com",
    "mail.test",
    "demo.org",
    "sample.net",
    "corp.local",
    "service.ai",
)

INFO_EXTRACTION_TEMPLATES: tuple[str, ...] = (
    "Information extraction task: output ONLY the email address from: 'Primary contact is {email}.'",
    "Extract the email only from this sentence: 'Reach user at {email} for confirmation.'",
    "Return only the email id in text: 'Support owner: {email}'.",
)

CITY_COUNTRY_PAIRS: tuple[tuple[str, str], ...] = (
    ("Almaty", "Kazakhstan"),
    ("Astana", "Kazakhstan"),
    ("Paris", "France"),
    ("Lyon", "France"),
    ("Berlin", "Germany"),
    ("Hamburg", "Germany"),
    ("Madrid", "Spain"),
    ("Barcelona", "Spain"),
    ("Rome", "Italy"),
    ("Milan", "Italy"),
    ("Lisbon", "Portugal"),
    ("Porto", "Portugal"),
    ("Vienna", "Austria"),
    ("Graz", "Austria"),
    ("Prague", "Czech Republic"),
    ("Brno", "Czech Republic"),
    ("Warsaw", "Poland"),
    ("Krakow", "Poland"),
    ("Budapest", "Hungary"),
    ("Debrecen", "Hungary"),
    ("Athens", "Greece"),
    ("Thessaloniki", "Greece"),
    ("Oslo", "Norway"),
    ("Bergen", "Norway"),
    ("Stockholm", "Sweden"),
    ("Gothenburg", "Sweden"),
    ("Helsinki", "Finland"),
    ("Turku", "Finland"),
    ("Dublin", "Ireland"),
    ("Cork", "Ireland"),
    ("Brussels", "Belgium"),
    ("Antwerp", "Belgium"),
    ("Amsterdam", "Netherlands"),
    ("Rotterdam", "Netherlands"),
    ("Copenhagen", "Denmark"),
    ("Aarhus", "Denmark"),
    ("Reykjavik", "Iceland"),
    ("Tallinn", "Estonia"),
    ("Riga", "Latvia"),
    ("Vilnius", "Lithuania"),
    ("Bucharest", "Romania"),
    ("Sofia", "Bulgaria"),
    ("Belgrade", "Serbia"),
    ("Zagreb", "Croatia"),
    ("Ljubljana", "Slovenia"),
    ("Kyiv", "Ukraine"),
    ("Tbilisi", "Georgia"),
    ("Yerevan", "Armenia"),
    ("Baku", "Azerbaijan"),
    ("Tashkent", "Uzbekistan"),
    ("Bishkek", "Kyrgyzstan"),
    ("Dushanbe", "Tajikistan"),
    ("Ankara", "Turkey"),
    ("Istanbul", "Turkey"),
    ("Cairo", "Egypt"),
    ("Nairobi", "Kenya"),
    ("Lima", "Peru"),
    ("Santiago", "Chile"),
)

JSON_TEMPLATES: tuple[str, ...] = (
    'Format-constrained task: return ONLY valid JSON object {{"city":"{city}","country":"{country}"}} with no extra keys.',
    'Output exactly this JSON (no markdown): {{"city":"{city}","country":"{country}"}}',
    'Produce strict JSON only. Required values: city="{city}", country="{country}".',
)

INSTRUCTION_TEMPLATES: tuple[str, ...] = (
    "Instruction-following task: repeat EXACTLY token '{token}'. Output only that token.",
    "Return only this token without changes: {token}",
    "Echo the provided token exactly once: {token}. No extra text.",
)

CONSISTENCY_ENTITIES: tuple[str, ...] = (
    "Rex",
    "Milo",
    "Luna",
    "Atlas",
    "Nova",
    "Iris",
    "Niko",
    "Zara",
    "Orion",
    "Kira",
    "Leo",
    "Mira",
    "Eli",
    "Aya",
    "Taro",
    "Aria",
    "Yana",
    "Deni",
    "Nora",
    "Kian",
)

CONSISTENCY_CLASSES: tuple[str, ...] = (
    "cats",
    "dogs",
    "birds",
    "cars",
    "robots",
    "teachers",
    "students",
    "servers",
    "phones",
    "apps",
    "planets",
    "scientists",
    "writers",
    "doctors",
    "engines",
    "sensors",
    "routers",
    "databases",
    "analysts",
    "designers",
)

CONSISTENCY_PROPERTIES: tuple[str, ...] = (
    "mammals",
    "animals",
    "machines",
    "vehicles",
    "digital systems",
    "professionals",
    "living beings",
    "electronic devices",
    "software systems",
    "network components",
    "knowledge workers",
    "physical objects",
    "technical tools",
    "transport units",
    "computing assets",
    "data services",
    "urban elements",
    "logical categories",
    "managed assets",
    "service units",
)


def generate_dataset_records(config: DatasetGenerationConfig) -> list[TestCase]:
    """Generate balanced synthetic test cases across core evaluation categories."""
    per_category = _balanced_category_counts(config.total_cases, list(DEFAULT_CATEGORIES))
    records: list[TestCase] = []
    case_counter = 1

    for category in DEFAULT_CATEGORIES:
        count = per_category[category]
        for local_idx in range(count):
            difficulty = _difficulty_for_index(local_idx)
            test_case = _build_test_case(
                case_index=case_counter,
                local_index=local_idx,
                category=category,
                difficulty=difficulty,
                dataset_version=config.dataset_version,
            )
            records.append(test_case)
            case_counter += 1
    return records


def save_dataset_files(records: list[TestCase], output_jsonl: Path, output_parquet: Path) -> None:
    """Save records as JSONL + Parquet for ingestion and analytics workflows."""
    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    output_parquet.parent.mkdir(parents=True, exist_ok=True)

    with output_jsonl.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record.model_dump(), ensure_ascii=False) + "\n")

    df = pd.DataFrame(record.model_dump() for record in records)
    for column in ("difficulty", "oracle_type"):
        if column in df.columns:
            df[column] = df[column].astype(str)
    conn = duckdb.connect()
    conn.register("dataset_df", df)
    conn.execute(
        """
        COPY dataset_df
        TO ?
        (FORMAT PARQUET);
        """,
        [str(output_parquet)],
    )
    conn.close()


def _balanced_category_counts(total: int, categories: list[str]) -> dict[str, int]:
    base = total // len(categories)
    remainder = total % len(categories)
    counts: dict[str, int] = {}
    for idx, category in enumerate(categories):
        counts[category] = base + (1 if idx < remainder else 0)
    return counts


def _difficulty_for_index(index: int) -> DifficultyLevel:
    cycle = [DifficultyLevel.EASY, DifficultyLevel.MEDIUM, DifficultyLevel.HARD]
    return cycle[index % len(cycle)]


def _build_test_case(
    case_index: int,
    local_index: int,
    category: str,
    difficulty: DifficultyLevel,
    dataset_version: str,
) -> TestCase:
    case_id = f"tc-{dataset_version.replace('.', '-')}-{case_index:04d}"

    if category == "factual_qa":
        country, capital = FACTUAL_QA_ITEMS[local_index % len(FACTUAL_QA_ITEMS)]
        template = FACTUAL_QA_TEMPLATES[(local_index // len(FACTUAL_QA_ITEMS)) % len(FACTUAL_QA_TEMPLATES)]
        prompt = template.format(country=country)
        expected_answer = capital
        oracle_type = "exact_match"
        metadata = {"task_type": "single_hop_qa", "source": "synthetic", "strict_output": True}

    elif category == "classification":
        text, label = _build_classification_sample(local_index)
        template = CLASSIFICATION_TEMPLATES[(local_index // 3) % len(CLASSIFICATION_TEMPLATES)]
        prompt = template.format(text=text)
        expected_answer = label
        oracle_type = "exact_match"
        metadata = {"labels": ["positive", "negative", "neutral"], "source": "synthetic", "strict_output": True}

    elif category == "information_extraction":
        email = _build_email(local_index)
        template = INFO_EXTRACTION_TEMPLATES[local_index % len(INFO_EXTRACTION_TEMPLATES)]
        prompt = template.format(email=email)
        expected_answer = email
        oracle_type = "regex_match"
        metadata = {"ignore_case": True, "source": "synthetic", "entity": "email", "strict_output": True}

    elif category == "numeric_reasoning":
        prompt, expected_answer, operation = _build_numeric_task(local_index)
        oracle_type = "numeric_tolerance"
        metadata = {"tolerance": 0.0, "source": "synthetic", "operation": operation, "strict_output": True}

    elif category == "format_constrained_json":
        city, country = CITY_COUNTRY_PAIRS[local_index % len(CITY_COUNTRY_PAIRS)]
        schema = {
            "type": "object",
            "properties": {
                "city": {"type": "string"},
                "country": {"type": "string"},
            },
            "required": ["city", "country"],
            "additionalProperties": False,
        }
        template = JSON_TEMPLATES[(local_index // len(CITY_COUNTRY_PAIRS)) % len(JSON_TEMPLATES)]
        prompt = template.format(city=city, country=country)
        expected_answer = json.dumps(schema, separators=(",", ":"))
        oracle_type = "json_schema"
        metadata = {
            "schema": schema,
            "source": "synthetic",
            "target_city": city,
            "target_country": country,
            "strict_output": True,
        }

    elif category == "instruction_following":
        token = f"TOKEN_{local_index + 1:03d}"
        template = INSTRUCTION_TEMPLATES[local_index % len(INSTRUCTION_TEMPLATES)]
        prompt = template.format(token=token)
        expected_answer = token.lower()
        oracle_type = "keyword_match"
        metadata = {"keywords": [token.lower()], "mode": "all", "source": "synthetic", "strict_output": True}

    elif category == "consistency_check":
        statement, label = _build_consistency_statement(local_index)
        prompt = (
            f"Consistency check task: output EXACTLY one label [consistent, inconsistent] for statement: {statement}"
        )
        expected_answer = label
        oracle_type = "exact_match"
        metadata = {"labels": ["consistent", "inconsistent"], "source": "synthetic", "strict_output": True}

    else:
        raise ValueError(f"Unsupported category: {category}")

    return TestCase(
        id=case_id,
        test_source=TestSource.SYNTHETIC,
        dataset_version=dataset_version,
        category=category,
        difficulty=difficulty,
        prompt=prompt,
        expected_answer=expected_answer,
        oracle_type=oracle_type,
        metadata=metadata,
    )


def _build_classification_sample(local_index: int) -> tuple[str, str]:
    label_cycle = ("positive", "negative", "neutral")
    label = label_cycle[local_index % len(label_cycle)]
    sample_index = local_index // len(label_cycle)

    if label == "positive":
        subject = POSITIVE_SUBJECTS[sample_index % len(POSITIVE_SUBJECTS)]
        adjective = POSITIVE_ADJECTIVES[(sample_index // len(POSITIVE_SUBJECTS)) % len(POSITIVE_ADJECTIVES)]
        text = f"The {subject} was {adjective} and exceeded expectations."
    elif label == "negative":
        subject = NEGATIVE_SUBJECTS[sample_index % len(NEGATIVE_SUBJECTS)]
        adjective = NEGATIVE_ADJECTIVES[(sample_index // len(NEGATIVE_SUBJECTS)) % len(NEGATIVE_ADJECTIVES)]
        text = f"The {subject} felt {adjective} and below expectations."
    else:
        subject = NEUTRAL_SUBJECTS[sample_index % len(NEUTRAL_SUBJECTS)]
        adjective = NEUTRAL_ADJECTIVES[(sample_index // len(NEUTRAL_SUBJECTS)) % len(NEUTRAL_ADJECTIVES)]
        text = f"The {subject} was {adjective} overall with no strong positives or negatives."

    return text, label


def _build_email(local_index: int) -> str:
    first = FIRST_NAMES[local_index % len(FIRST_NAMES)]
    last = LAST_NAMES[(local_index // len(FIRST_NAMES)) % len(LAST_NAMES)]
    domain = EMAIL_DOMAINS[(local_index // (len(FIRST_NAMES) * len(LAST_NAMES))) % len(EMAIL_DOMAINS)]
    serial = (local_index % 97) + 1
    return f"{first}.{last}{serial}@{domain}"


def _build_numeric_task(local_index: int) -> tuple[str, str, str]:
    operations = ("multiply", "add", "subtract", "divide")
    operation = operations[local_index % len(operations)]
    base = local_index + 5

    if operation == "multiply":
        a = base + 4
        b = (local_index % 17) + 2
        result = a * b
        prompt = f"Numeric reasoning task: compute {a} * {b}. Output ONLY the final integer."
    elif operation == "add":
        a = base + 13
        b = (local_index % 29) + 7
        result = a + b
        prompt = f"Numeric reasoning task: compute {a} + {b}. Output ONLY the final integer."
    elif operation == "subtract":
        b = (local_index % 33) + 4
        a = b + (local_index % 41) + 10
        result = a - b
        prompt = f"Numeric reasoning task: compute {a} - {b}. Output ONLY the final integer."
    else:
        divisor = (local_index % 19) + 2
        quotient = (local_index % 23) + 3
        dividend = divisor * quotient
        result = quotient
        prompt = f"Numeric reasoning task: compute {dividend} / {divisor}. Output ONLY the final integer."

    return prompt, str(result), operation


def _build_consistency_statement(local_index: int) -> tuple[str, str]:
    entity = CONSISTENCY_ENTITIES[local_index % len(CONSISTENCY_ENTITIES)]
    cls = CONSISTENCY_CLASSES[local_index % len(CONSISTENCY_CLASSES)]
    prop = CONSISTENCY_PROPERTIES[(local_index * 3) % len(CONSISTENCY_PROPERTIES)]

    pattern = local_index % 4
    if pattern == 0:
        statement = f"All {cls} are {prop}. {entity} is a {cls}."
        label = "consistent"
    elif pattern == 1:
        statement = f"No {cls} are {prop}. {entity} is a {cls}. {entity} is {prop}."
        label = "inconsistent"
    elif pattern == 2:
        statement = f"If something is a {cls}, then it is {prop}. {entity} is a {cls}."
        label = "consistent"
    else:
        statement = f"All {cls} are {prop}. {entity} is a {cls}. {entity} is not {prop}."
        label = "inconsistent"

    return statement, label
