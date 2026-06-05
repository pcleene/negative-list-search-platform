"""
MB Negative List — Seed Script
================================
Generates 5,000 realistic Filipino negative-list entries, computes Voyage AI
embeddings for every document, bulk-inserts into MongoDB Atlas, and creates
both the Atlas Search (fuzzy) and Atlas Vector Search indexes.

Usage:
    python -m backend.seed.seed_negative_list
"""

from __future__ import annotations

import asyncio
import random
import string
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from pymongo import AsyncMongoClient

# ── Configuration ────────────────────────────────────────────────────────────

MONGO_URI = (
    "mongodb+srv://<user>:<password>@<cluster>.mongodb.net/<db>"
    "?authSource=%24external&authMechanism=MONGODB-X509&appName=testCluster"
)
TLS_CERT_PATH = "<local-path>"
DB_NAME = "mb_negative_list"
COLLECTION_NAME = "negative_list"

VOYAGE_API_KEY = "<voyage-key>"
VOYAGE_MODEL = "voyage-4-large"
VOYAGE_DIMENSIONS = 1024
VOYAGE_ENDPOINT = "https://api.voyageai.com/v1/embeddings"
VOYAGE_BATCH_SIZE = 128  # Voyage AI max inputs per call

TOTAL_ENTRIES = 5000

# ── Name Pools ───────────────────────────────────────────────────────────────

FILIPINO_MALE_FIRST = [
    "Juan", "Jose", "Pedro", "Antonio", "Carlos", "Ricardo", "Fernando",
    "Rafael", "Miguel", "Gabriel", "Marco", "Paolo", "Angelo", "Rodrigo",
    "Andres", "Emilio", "Ramon", "Eduardo", "Roberto", "Francisco",
    "Mark", "John", "Michael", "James", "Christian", "Kenneth", "Ryan",
    "Kevin", "Patrick", "Daniel", "Jayson", "Rodel", "Arnel", "Ernesto",
    "Dante", "Romeo", "Voltaire", "Crisanto", "Benigno", "Renato",
]

FILIPINO_FEMALE_FIRST = [
    "Maria", "Ana", "Rosa", "Carmen", "Josefina", "Teresita", "Cristina",
    "Lourdes", "Milagros", "Corazon", "Imelda", "Estrella", "Rosalinda",
    "Patricia", "Angela", "Michelle", "Jennifer", "Catherine", "Nicole",
    "Andrea", "Stephanie", "Jasmine", "Angelica", "Denise", "Grace",
    "Faith", "Joy", "Hope", "Cherry", "Apple", "Princess", "Divine",
    "Precious", "Lovely", "Marites", "Rowena", "Liza", "Nora", "Gloria",
    "Carmelita",
]

FILIPINO_FAMILY = [
    "Santos", "Reyes", "Cruz", "Bautista", "Ocampo", "Garcia", "Mendoza",
    "Torres", "Tomas", "Andrada", "Villanueva", "Ramos", "Aquino",
    "Gonzales", "Hernandez", "Lopez", "Martinez", "Rodriguez", "Perez",
    "Flores", "Rivera", "Morales", "Cacme", "Diaz", "Fernandez",
    "Aguilar", "Navarro", "Soriano", "Salvador", "Manalo", "Pascual",
    "Santiago", "Concepcion", "Mercado", "Evangelista", "Panganiban",
    "Tolentino", "Magno", "Corpuz", "Enriquez",
]

FILIPINO_COMPOUND_FAMILY = [
    "Dela Cruz", "De la Cruz", "De los Santos", "Delos Reyes",
    "Del Rosario", "De Leon", "De Guzman", "De Cacme", "Del Mundo",
    "De Jesus", "De Vera", "Dela Rosa", "De Asis", "Del Valle",
    "De Ocampo", "Delos Angeles",
]

CHINESE_FILIPINO_FAMILY = [
    "Tan", "Lim", "Ong", "Go", "Chua", "Sy", "Co", "Ty", "Uy",
    "Yap", "Ang", "Chan", "Lee", "Wong", "Cheng", "Huang", "Yu",
    "Tiu", "Que", "Dee", "Dy", "Kho", "Ngo", "Lua",
]

METRO_MANILA_CITIES = [
    "Makati", "Taguig", "Pasig", "Mandaluyong", "Quezon City",
    "Manila", "San Juan", "Pasay", "Parañaque", "Muntinlupa",
    "Las Piñas", "Caloocan", "Malabon", "Navotas", "Valenzuela",
    "Marikina", "Pateros",
]

PROVINCES = [
    "Cebu", "Davao del Sur", "Pampanga", "Bulacan", "Laguna",
    "Cavite", "Batangas", "Rizal", "Pangasinan", "Iloilo",
    "Negros Occidental", "Leyte", "Zamboanga del Sur", "Cagayan",
    "Misamis Oriental", "Albay", "Camarines Sur",
]

MB_BRANCHES = [
    "Makati Main", "BGC Flagship", "Ayala Center Cebu", "Ortigas Center",
    "Alabang Town Center", "Eastwood City", "SM Megamall", "Greenbelt 1",
    "Quezon Ave", "Davao Main", "Iloilo Business Center", "Clark Freeport",
    "SM Mall of Asia", "Robinsons Galleria", "Trinoma", "SM North EDSA",
]

# ── Negative Reason Definitions ──────────────────────────────────────────────

NEGATIVE_REASONS = {
    "LOAN_DEFAULT": "Defaulted on any loan product",
    "CC_CANCELLED": "Credit card cancelled for non-payment",
    "CC_OVERLIMIT": "Chronic credit card over-limit abuse",
    "FRAUD_CONFIRMED": "Confirmed fraudulent activity",
    "FRAUD_SUSPECTED": "Suspected fraud (under investigation)",
    "CHECK_BOUNCING": "Repeated check bouncing / DAIF",
    "AML_FLAG": "Anti-Money Laundering flag from AMLC",
    "IDENTITY_THEFT": "Identity theft involvement",
    "ACCOUNT_ABUSE": "Account misuse / abuse",
    "BANKRUPTCY": "Declared bankruptcy",
    "GARNISHMENT": "Account garnished by court order",
    "ESTAFA": "Estafa / swindling conviction",
}

WATCHLIST_SOURCES = [
    "MB Internal", "AMLC", "BSP", "OFAC", "UN Sanctions", "EU Sanctions",
    "NBI", "PNP-CIDG", "SEC Philippines", "CISS", "BAP", "PDIC",
]

WATCHLIST_CATEGORIES = [
    "Financial Crime", "Money Laundering", "Terrorism Financing",
    "Fraud", "Sanctions", "Regulatory", "Criminal", "Internal",
]

# ── Product / Account Constants ──────────────────────────────────────────────

SAVINGS_PRODUCTS = [
    "MB Savings Account", "MB Family Savings", "MB Pamana Savings",
    "MB Maxi-Saver", "MB Easy Saver",
]
CHECKING_PRODUCTS = [
    "MB Checking Account", "MB Express Checking",
]
CC_PRODUCTS = [
    "MB Gold Mastercard", "MB Blue Mastercard", "MB Visa Signature",
    "MB Amore Visa", "MB SIA Visa", "MB Edge Mastercard",
    "MB Petron Mastercard", "MB Real Thrills Mastercard",
]
LOAN_PRODUCTS = [
    "MB Personal Loan", "MB Auto Loan", "MB Housing Loan",
    "MB Ka-Negosyo Loan", "MB Salary Loan", "MB Credit Line",
]

RELATIONSHIP_SEGMENTS = ["Retail", "Preferred", "Wealth", "Private", "SME", "Corporate"]
RELATIONSHIP_TIERS = ["Standard", "Silver", "Gold", "Platinum", "Diamond"]
KYC_LEVELS = ["Basic", "Standard", "Enhanced", "Full Due Diligence"]

COMPANY_SUFFIXES = [
    "Corp.", "Inc.", "Trading", "Enterprises", "Holdings",
    "Development Corp.", "Realty Inc.", "Construction Corp.",
    "Services Inc.", "Solutions Corp.", "Manufacturing Inc.",
    "Import-Export Corp.", "Logistics Inc.", "Ventures Inc.",
]

COMPANY_PREFIXES = [
    "Golden", "Royal", "Pacific", "Metro", "Prime", "Star", "Grand",
    "Mega", "Supreme", "Excel", "Pioneer", "Fortune", "Diamond",
    "Prestige", "National", "Allied", "Summit", "Victory", "Premier",
    "Eagle", "Horizon", "Superior", "Zenith", "Atlas", "Emerald",
]

GENERATIONAL_SUFFIXES = ["Jr.", "Sr.", "III", "II", "IV"]

# ── Atlas Search Index Definitions ───────────────────────────────────────────

FILIPINO_NAME_ANALYZER = {
    "name": "filipino_name_analyzer",
    "charFilters": [
        {
            "type": "mapping",
            "mappings": {
                " dela ": " ", " Dela ": " ", " DELA ": " ",
                " de la ": " ", " De La ": " ", " DE LA ": " ", " De la ": " ",
                " de los ": " ", " De Los ": " ", " DE LOS ": " ", " De los ": " ",
                " del ": " ", " Del ": " ", " DEL ": " ",
                " delos ": " ", " Delos ": " ", " DELOS ": " ",
                " de ": " ", " De ": " ", " DE ": " ",
                "Ma. ": "Maria ", "ma. ": "maria ", "MA. ": "MARIA ",
                " Jr.": "", " jr.": "", " JR.": "", " JR": "",
                " Sr.": "", " sr.": "", " SR.": "", " SR": "",
                " III": "", " II": "", " IV": "",
            },
        }
    ],
    "tokenizer": {"type": "standard"},
    "tokenFilters": [{"type": "lowercase"}],
}

FUZZY_INDEX = {
    "name": "negative_list_fuzzy",
    "definition": {
        "mappings": {
            "dynamic": False,
            "fields": {
                "fullName": [
                    {
                        "type": "string",
                        "analyzer": "filipino_name_analyzer",
                        "searchAnalyzer": "filipino_name_analyzer",
                    },
                    {
                        "type": "autocomplete",
                        "analyzer": "filipino_name_analyzer",
                        "tokenization": "edgeGram",
                        "minGrams": 2,
                        "maxGrams": 20,
                    },
                ],
                "aliases": [
                    {
                        "type": "string",
                        "analyzer": "filipino_name_analyzer",
                        "searchAnalyzer": "filipino_name_analyzer",
                    },
                    {
                        "type": "autocomplete",
                        "analyzer": "filipino_name_analyzer",
                        "tokenization": "edgeGram",
                        "minGrams": 2,
                        "maxGrams": 20,
                    },
                ],
                "identifiers.nationalId": [
                    {"type": "string"},
                    {
                        "type": "autocomplete",
                        "tokenization": "edgeGram",
                        "minGrams": 3,
                        "maxGrams": 20,
                    },
                ],
                "identifiers.tin": [
                    {"type": "string"},
                    {
                        "type": "autocomplete",
                        "tokenization": "edgeGram",
                        "minGrams": 3,
                        "maxGrams": 20,
                    },
                ],
                "dateOfBirth": {"type": "date"},
                "entityType": [{"type": "token"}, {"type": "stringFacet"}],
                "negativeReasonCodes": [{"type": "token"}, {"type": "stringFacet"}],
                "watchlistSourceNames": [{"type": "token"}, {"type": "stringFacet"}],
                "relationship": {
                    "type": "document",
                    "fields": {
                        "branch": [{"type": "token"}, {"type": "stringFacet"}],
                        "tier": [{"type": "token"}, {"type": "stringFacet"}],
                        "segment": [{"type": "token"}, {"type": "stringFacet"}],
                    },
                },
                "riskScore": [{"type": "number"}, {"type": "numberFacet"}],
                "riskTags": {"type": "token"},
                "isActive": {"type": "boolean"},
            },
        },
        "analyzers": [FILIPINO_NAME_ANALYZER],
    },
}

VECTOR_INDEX = {
    "name": "negative_list_vector",
    "type": "vectorSearch",
    "definition": {
        "fields": [
            {
                "type": "vector",
                "path": "embedding",
                "numDimensions": 1024,
                "similarity": "cosine",
            },
            {"type": "filter", "path": "isActive"},
            {"type": "filter", "path": "entityType"},
            {"type": "filter", "path": "riskScore"},
        ]
    },
}


# ── Serialization for Embeddings ─────────────────────────────────────────────


def serialize_for_embedding(doc: dict) -> str:
    """Convert a negative list document into rich text for Voyage AI embedding."""
    parts = [
        f"Name: {doc.get('fullName', '')}",
        f"Aliases: {', '.join(doc.get('aliases', []))}",
        f"Entity Type: {doc.get('entityType', '')}",
    ]

    rel = doc.get("relationship", {})
    if rel:
        parts.append(
            f"Customer: {rel.get('segment', '')} segment, "
            f"{rel.get('tier', '')} tier, "
            f"branch {rel.get('branch', '')}, "
            f"status {rel.get('status', '')}"
        )

    for acct in doc.get("accounts", []):
        parts.append(
            f"Account: {acct.get('type', '')} — {acct.get('productName', '')} — "
            f"status {acct.get('status', '')}"
        )

    for loan in doc.get("loans", []):
        parts.append(
            f"Loan: {loan.get('productName', '')} — "
            f"PHP {loan.get('outstandingBalance', 0):,.2f} outstanding — "
            f"status {loan.get('status', '')} — "
            f"{loan.get('missedPayments', 0)} missed payments"
        )

    for reason in doc.get("negativeReasons", []):
        parts.append(
            f"Negative: {reason.get('description', '')} — "
            f"{reason.get('productType', '')} — "
            f"PHP {reason.get('amount', 0):,.2f} — "
            f"Status: {reason.get('status', '')}"
        )

    for src in doc.get("watchlistSources", []):
        parts.append(f"Watchlist: {src.get('source', '')} — {src.get('category', '')}")

    tags = doc.get("riskTags", [])
    if tags:
        parts.append(f"Risk tags: {', '.join(tags)}")

    addr = doc.get("addresses", [{}])[0] if doc.get("addresses") else {}
    if addr:
        parts.append(f"Location: {addr.get('city', '')}, {addr.get('province', '')}")

    return " | ".join(parts)


# ── Random Data Helpers ──────────────────────────────────────────────────────


def _rand_date(start_year: int, end_year: int) -> datetime:
    """Random date between start_year-01-01 and end_year-12-31."""
    start = datetime(start_year, 1, 1, tzinfo=timezone.utc)
    end = datetime(end_year, 12, 31, tzinfo=timezone.utc)
    delta = end - start
    return start + timedelta(seconds=random.randint(0, int(delta.total_seconds())))


def _rand_phone() -> str:
    return f"+639{random.randint(100000000, 999999999)}"


def _rand_email(first: str, last: str) -> str:
    domains = [
        "gmail.com", "yahoo.com", "yahoo.com.ph", "hotmail.com",
        "outlook.com", "protonmail.com", "mail.com",
    ]
    slug = f"{first.lower().replace(' ', '').replace('.', '')}" \
           f".{last.lower().replace(' ', '').replace('.', '')}"
    return f"{slug}{random.randint(1, 999)}@{random.choice(domains)}"


def _rand_national_id() -> str:
    """Philippine national ID format: XXXX-XXXX-XXXX-XXXX."""
    groups = [
        "".join(random.choices(string.digits, k=4)) for _ in range(4)
    ]
    return "-".join(groups)


def _rand_tin() -> str:
    """TIN format: XXX-XXX-XXX-XXX."""
    groups = [
        "".join(random.choices(string.digits, k=3)) for _ in range(4)
    ]
    return "-".join(groups)


def _rand_passport() -> str:
    """Philippine passport: 1 letter + 7 digits."""
    return random.choice(string.ascii_uppercase) + "".join(
        random.choices(string.digits, k=7)
    )


def _rand_sss() -> str:
    """SSS number: XX-XXXXXXX-X."""
    return (
        f"{''.join(random.choices(string.digits, k=2))}-"
        f"{''.join(random.choices(string.digits, k=7))}-"
        f"{random.choice(string.digits)}"
    )


def _rand_account_number() -> str:
    return "".join(random.choices(string.digits, k=10))


def _rand_cc_number() -> str:
    """Masked credit card number."""
    return f"****-****-****-{''.join(random.choices(string.digits, k=4))}"


def _rand_address() -> dict:
    """Generate a random Filipino address."""
    use_metro = random.random() < 0.65
    if use_metro:
        city = random.choice(METRO_MANILA_CITIES)
        province = "Metro Manila"
    else:
        province = random.choice(PROVINCES)
        city = province  # Simplified: use province name as city for non-Metro

    barangays = [
        "Poblacion", "San Antonio", "Santa Cruz", "Bagumbayan", "Rizal",
        "Magsaysay", "Bonifacio", "Mabini", "Del Pilar", "Burgos",
        "San Isidro", "Santa Rosa", "San Jose", "Conception", "Pag-asa",
    ]

    return {
        "type": random.choice(["Home", "Business", "Mailing"]),
        "line1": f"{random.randint(1, 999)} {random.choice(['Rizal', 'Mabini', 'Bonifacio', 'Aguinaldo', 'Quezon', 'Osmena', 'Roxas', 'Magsaysay', 'Laurel', 'Garcia'])} St.",
        "line2": f"Brgy. {random.choice(barangays)}",
        "city": city,
        "province": province,
        "postalCode": f"{random.randint(1000, 9999)}",
        "country": "PH",
    }


def _generate_accounts(is_cc_issue: bool, branch: str) -> list[dict]:
    """Generate 1-3 bank accounts for a person."""
    num_accounts = random.randint(1, 3)
    accounts: list[dict] = []

    def _acct_status():
        return random.choice(["active", "dormant", "frozen", "closed"])

    # Always include at least one savings
    status = _acct_status()
    opened = _rand_date(2005, 2023)
    accounts.append({
        "type": "savings",
        "number": _rand_account_number(),
        "productName": random.choice(SAVINGS_PRODUCTS),
        "status": status,
        "branch": branch,
        "openedAt": opened,
        "closedAt": _rand_date(2023, 2025) if status == "closed" else None,
        "lastBalance": round(random.uniform(0, 500000), 2),
        "currency": "PHP",
    })

    if num_accounts >= 2:
        if is_cc_issue or random.random() < 0.5:
            cc_status = random.choice(["active", "suspended", "cancelled", "closed"])
            cc_limit = random.choice([50000, 100000, 200000, 300000, 500000, 1000000])
            cc_opened = _rand_date(2008, 2023)
            accounts.append({
                "type": "credit_card",
                "number": f"****{random.randint(1000,9999)}",
                "productName": random.choice(CC_PRODUCTS),
                "status": cc_status,
                "branch": branch,
                "openedAt": cc_opened,
                "closedAt": _rand_date(2023, 2025) if cc_status in ("cancelled", "closed") else None,
                "creditLimit": cc_limit,
                "outstandingBalance": round(random.uniform(0, cc_limit), 2) if cc_status in ("cancelled", "suspended") else 0.0,
                "currency": "PHP",
            })
        else:
            chk_status = _acct_status()
            chk_opened = _rand_date(2008, 2023)
            accounts.append({
                "type": "checking",
                "number": _rand_account_number(),
                "productName": random.choice(CHECKING_PRODUCTS),
                "status": chk_status,
                "branch": branch,
                "openedAt": chk_opened,
                "closedAt": _rand_date(2023, 2025) if chk_status == "closed" else None,
                "lastBalance": round(random.uniform(0, 200000), 2),
                "currency": "PHP",
            })

    if num_accounts >= 3:
        cc_status = random.choice(["active", "suspended", "cancelled"])
        cc_limit = random.choice([50000, 100000, 200000, 300000, 500000])
        cc_opened = _rand_date(2010, 2024)
        accounts.append({
            "type": "credit_card",
            "number": f"****{random.randint(1000,9999)}",
            "productName": random.choice(CC_PRODUCTS),
            "status": cc_status,
            "branch": branch,
            "openedAt": cc_opened,
            "closedAt": _rand_date(2023, 2025) if cc_status == "cancelled" else None,
            "creditLimit": cc_limit,
            "outstandingBalance": round(random.uniform(0, cc_limit), 2) if cc_status in ("cancelled", "suspended") else 0.0,
            "currency": "PHP",
        })

    return accounts


def _generate_loans(has_loan_default: bool, branch: str = "Makati Main") -> list[dict]:
    """Generate 0-2 loans."""
    num_loans = random.randint(0, 2)
    if has_loan_default and num_loans == 0:
        num_loans = 1

    loan_types = ["personal", "auto", "housing", "business"]
    terms = ["12 months", "24 months", "36 months", "48 months", "60 months", "120 months"]
    loans: list[dict] = []
    for _ in range(num_loans):
        principal = random.choice([50000, 100000, 200000, 500000, 1000000, 2000000, 5000000])
        outstanding = round(principal * random.uniform(0.1, 1.0), 2)
        status = "defaulted" if has_loan_default and not loans else random.choice(
            ["current", "past_due", "defaulted", "restructured", "paid"]
        )
        missed = random.randint(3, 24) if status in ("defaulted", "past_due") else 0
        disbursed = _rand_date(2010, 2022)
        loans.append({
            "type": random.choice(loan_types),
            "loanId": f"PL-{disbursed.year}-{random.randint(10000,99999):05d}",
            "productName": random.choice(LOAN_PRODUCTS),
            "principalAmount": principal,
            "outstandingBalance": outstanding,
            "interestRate": round(random.uniform(0.5, 2.5), 1),
            "term": random.choice(terms),
            "status": status,
            "disbursedAt": disbursed,
            "defaultedAt": _rand_date(2022, 2025) if status == "defaulted" else None,
            "lastPaymentAt": _rand_date(2022, 2025) if missed > 0 else None,
            "missedPayments": missed,
            "branch": branch,
            "currency": "PHP",
        })

    return loans


def _pick_negative_reasons(category: str, count: int) -> list[dict]:
    """
    Generate negative reason entries based on the assigned category.
    category: 'loan', 'cc', 'fraud', 'aml'
    count: how many reasons (1 for single, 2-3 for repeat offenders)
    """
    reason_map = {
        "loan": ["LOAN_DEFAULT", "CHECK_BOUNCING", "BANKRUPTCY", "GARNISHMENT"],
        "cc": ["CC_CANCELLED", "CC_OVERLIMIT", "ACCOUNT_ABUSE"],
        "fraud": ["FRAUD_CONFIRMED", "FRAUD_SUSPECTED", "IDENTITY_THEFT", "ESTAFA"],
        "aml": ["AML_FLAG", "FRAUD_SUSPECTED", "ACCOUNT_ABUSE"],
    }

    product_map = {
        "LOAN_DEFAULT": "Loan",
        "CC_CANCELLED": "Credit Card",
        "CC_OVERLIMIT": "Credit Card",
        "FRAUD_CONFIRMED": random.choice(["Deposit", "Credit Card", "Loan"]),
        "FRAUD_SUSPECTED": random.choice(["Deposit", "Credit Card", "Loan"]),
        "CHECK_BOUNCING": "Checking",
        "AML_FLAG": "Deposit",
        "IDENTITY_THEFT": random.choice(["Deposit", "Credit Card"]),
        "ACCOUNT_ABUSE": random.choice(["Deposit", "Credit Card"]),
        "BANKRUPTCY": "Multiple",
        "GARNISHMENT": "Deposit",
        "ESTAFA": random.choice(["Deposit", "Loan"]),
    }

    codes = reason_map.get(category, ["LOAN_DEFAULT"])
    primary = codes[0]
    selected_codes = [primary]

    # Pick additional reasons if repeat offender
    all_codes = list(NEGATIVE_REASONS.keys())
    for _ in range(count - 1):
        extra = random.choice([c for c in all_codes if c not in selected_codes])
        selected_codes.append(extra)

    reasons = []
    for code in selected_codes:
        amount = round(random.uniform(10000, 5000000), 2)
        flagged = _rand_date(2018, 2025)
        reasons.append({
            "code": code,
            "description": NEGATIVE_REASONS[code],
            "amount": amount,
            "currency": "PHP",
            "dateRecorded": flagged,
            "productType": product_map.get(code, "Deposit"),
            "accountRef": f"{code[:2]}-{_rand_date(2018,2023).year}-{random.randint(10000,99999):05d}",
            "status": random.choice(["unresolved", "under_review", "escalated"]),
        })

    return reasons


def _pick_watchlist_sources(reason_codes: list[str]) -> list[dict]:
    """Pick 1-3 watchlist sources based on the reason codes."""
    # Always include MB Internal
    sources = [{"source": "MB Internal", "category": "Internal", "addedAt": _rand_date(2019, 2025), "isActive": True}]

    aml_codes = {"AML_FLAG", "FRAUD_CONFIRMED", "FRAUD_SUSPECTED"}
    if aml_codes & set(reason_codes):
        sources.append({
            "source": random.choice(["AMLC", "BSP", "OFAC"]),
            "category": random.choice(["Money Laundering", "Terrorism Financing", "Sanctions"]),
            "addedAt": _rand_date(2019, 2025),
            "isActive": True,
        })

    fraud_codes = {"FRAUD_CONFIRMED", "IDENTITY_THEFT", "ESTAFA"}
    if fraud_codes & set(reason_codes):
        sources.append({
            "source": random.choice(["NBI", "PNP-CIDG"]),
            "category": "Criminal",
            "addedAt": _rand_date(2019, 2025),
            "isActive": True,
        })

    # Randomly add more sources
    if random.random() < 0.2:
        extra = random.choice(["BAP", "CISS", "PDIC", "SEC Philippines", "UN Sanctions", "EU Sanctions"])
        if not any(s["source"] == extra for s in sources):
            sources.append({
                "source": extra,
                "category": random.choice(WATCHLIST_CATEGORIES),
                "addedAt": _rand_date(2020, 2025),
                "isActive": True,
            })

    return sources


def _compute_risk_score(reasons: list[dict], watchlist_sources: list[dict]) -> float:
    """Deterministic risk score: 0.0-1.0 float based on severity."""
    base = 30
    severity = {
        "FRAUD_CONFIRMED": 25, "ESTAFA": 25, "AML_FLAG": 25,
        "FRAUD_SUSPECTED": 15, "IDENTITY_THEFT": 20,
        "LOAN_DEFAULT": 10, "BANKRUPTCY": 15, "GARNISHMENT": 12,
        "CC_CANCELLED": 8, "CC_OVERLIMIT": 5, "CHECK_BOUNCING": 8,
        "ACCOUNT_ABUSE": 10,
    }
    for r in reasons:
        base += severity.get(r["code"], 5)

    external_count = sum(1 for s in watchlist_sources if s["source"] != "MB Internal")
    base += external_count * 5

    return round(min(100, base) / 100.0, 2)


def _risk_tags(reasons: list[dict], risk_score: int) -> list[str]:
    """Derive risk tags from reason codes and score."""
    tags = set()
    codes = {r["code"] for r in reasons}

    if codes & {"FRAUD_CONFIRMED", "FRAUD_SUSPECTED", "IDENTITY_THEFT", "ESTAFA"}:
        tags.add("fraud_risk")
    if codes & {"AML_FLAG"}:
        tags.add("aml_risk")
    if codes & {"LOAN_DEFAULT", "BANKRUPTCY"}:
        tags.add("loan_default")
    if codes & {"CC_CANCELLED", "CC_OVERLIMIT"}:
        tags.add("cc_nonpayment")
    if codes & {"CHECK_BOUNCING"}:
        tags.add("check_bouncing")
    if codes & {"GARNISHMENT"}:
        tags.add("legal_action")
    if len(reasons) >= 2:
        tags.add("repeat_offender")
    if risk_score >= 0.8:
        tags.add("high_risk")
    elif risk_score >= 0.5:
        tags.add("medium_risk")
    else:
        tags.add("low_risk")

    return sorted(tags)


# ── Person Entry Generator ───────────────────────────────────────────────────


def _generate_person_name() -> tuple[str, str, str, list[str]]:
    """
    Returns (first_name, last_name, full_name, aliases).
    Includes Ma./Maria variants, compound surname variants, Chinese-Filipino names.
    """
    is_female = random.random() < 0.5
    use_ma_prefix = False

    # Pick first name
    if is_female:
        first = random.choice(FILIPINO_FEMALE_FIRST)
        # ~15% chance of "Ma." variant for Maria
        if first == "Maria" and random.random() < 0.15:
            use_ma_prefix = True
    else:
        first = random.choice(FILIPINO_MALE_FIRST)

    # Optionally add a middle name
    middle = ""
    if random.random() < 0.4:
        if is_female:
            middle = random.choice(FILIPINO_FEMALE_FIRST)
        else:
            middle = random.choice(FILIPINO_MALE_FIRST)

    # Pick last name — weighted distribution
    surname_roll = random.random()
    if surname_roll < 0.20:
        # 20% compound surnames
        last = random.choice(FILIPINO_COMPOUND_FAMILY)
    elif surname_roll < 0.35:
        # 15% Chinese-Filipino
        last = random.choice(CHINESE_FILIPINO_FAMILY)
    else:
        # 65% standard Filipino
        last = random.choice(FILIPINO_FAMILY)

    # Generational suffix (~10%)
    suffix = ""
    if not is_female and random.random() < 0.10:
        suffix = random.choice(GENERATIONAL_SUFFIXES)

    # Build full name
    display_first = f"Ma. {first[5:]}" if use_ma_prefix and first.startswith("Maria") else first
    # For "Maria" -> "Ma." variant: use "Ma." in full name
    if use_ma_prefix:
        display_first = "Ma."
        # Add the rest of the first name if applicable (e.g., "Maria Cristina" -> "Ma. Cristina")
        if middle:
            display_first = f"Ma. {middle}"
            middle = ""  # Already incorporated

    name_parts = [display_first]
    if middle:
        name_parts.append(middle)
    name_parts.append(last)
    if suffix:
        name_parts.append(suffix)

    full_name = " ".join(name_parts)

    # Generate aliases
    aliases: list[str] = []

    # Ma. / Maria variant alias
    if use_ma_prefix:
        alias_parts = [full_name.replace("Ma.", "Maria", 1)]
        aliases.append(alias_parts[0])
    elif is_female and first == "Maria":
        # The canonical form is "Maria", add "Ma." alias
        alias_name = full_name.replace("Maria", "Ma.", 1)
        aliases.append(alias_name)

    # Compound surname variant aliases
    compound_variants = {
        "Dela Cruz": "De la Cruz", "De la Cruz": "Dela Cruz",
        "Delos Reyes": "De los Reyes", "De los Santos": "Delos Santos",
        "Del Rosario": "del Rosario", "De Leon": "de Leon",
        "De Guzman": "de Guzman", "De Cacme": "de Cacme",
        "Del Mundo": "del Mundo", "De Jesus": "de Jesus",
        "De Vera": "de Vera", "Dela Rosa": "De la Rosa",
        "De Asis": "de Asis", "Del Valle": "del Valle",
        "De Ocampo": "de Ocampo", "Delos Angeles": "De los Angeles",
    }
    if last in compound_variants:
        variant_last = compound_variants[last]
        alias = full_name.replace(last, variant_last, 1)
        if alias not in aliases:
            aliases.append(alias)

    # Nickname alias (~20%)
    if random.random() < 0.20:
        nicknames = {
            "Ricardo": "Ricky", "Fernando": "Nando", "Eduardo": "Eddie",
            "Francisco": "Paco", "Roberto": "Bobby", "Antonio": "Tony",
            "Patricia": "Patty", "Cristina": "Tina", "Rosalinda": "Linda",
            "Jennifer": "Jenny", "Catherine": "Cathy", "Angelica": "Angel",
            "Teresita": "Tessie", "Josefina": "Josie", "Carmelita": "Carmie",
            "Michelle": "Mich", "Stephanie": "Steph", "Michael": "Mike",
        }
        if first in nicknames:
            nick = nicknames[first]
            alias = full_name.replace(first if not use_ma_prefix else "Ma.", nick, 1)
            if alias not in aliases:
                aliases.append(alias)

    return first, last, full_name, aliases


def _generate_person_entry(idx: int, category: str, is_repeat: bool, is_resolved: bool) -> dict:
    """Generate a single person negative list entry."""
    first, last, full_name, aliases = _generate_person_name()

    dob = _rand_date(1955, 2000)
    flagged_date = _rand_date(2018, 2025)

    num_reasons = random.randint(2, 3) if is_repeat else 1
    reasons = _pick_negative_reasons(category, num_reasons)
    reason_codes = [r["code"] for r in reasons]
    watchlist_sources = _pick_watchlist_sources(reason_codes)
    risk_score = _compute_risk_score(reasons, watchlist_sources)
    tags = _risk_tags(reasons, risk_score)

    is_active = not is_resolved
    if is_resolved:
        for r in reasons:
            r["status"] = "resolved"

    has_loan_default = any(r["code"] == "LOAN_DEFAULT" for r in reasons)
    is_cc_issue = any(r["code"] in ("CC_CANCELLED", "CC_OVERLIMIT") for r in reasons)

    branch = random.choice(MB_BRANCHES)
    segment = random.choice(["retail", "preferred", "wealth", "private"])
    tier = random.choice(["standard", "silver", "gold", "platinum", "diamond"])
    is_female = first in FILIPINO_FEMALE_FIRST
    rm_first = random.choice(FILIPINO_MALE_FIRST + FILIPINO_FEMALE_FIRST)
    rm_last = random.choice(FILIPINO_FAMILY)

    now = datetime.now(timezone.utc)
    rel_since = _rand_date(2000, 2020)

    return {
        "entityId": f"MB-NEG-{idx + 1:06d}",
        "entityType": "person",
        "fullName": full_name,
        "aliases": aliases,
        "dateOfBirth": dob,
        "gender": "F" if is_female else "M",
        "phone": _rand_phone(),
        "email": _rand_email(first, last),
        "civilStatus": random.choice(["single", "married", "widowed", "separated"]),
        "nationality": "Filipino",
        "identifiers": {
            "nationalId": _rand_national_id(),
            "tin": _rand_tin(),
            "sssNo": _rand_sss(),
            "gsisNo": None,
            "passportNo": _rand_passport() if random.random() < 0.6 else None,
            "driversLicense": f"N{random.randint(1,9)}{random.randint(0,9)}-{random.randint(10,99)}-{random.randint(100000,999999)}" if random.random() < 0.4 else None,
        },
        "addresses": [_rand_address()] + ([_rand_address()] if random.random() < 0.3 else []),
        "accounts": _generate_accounts(is_cc_issue, branch),
        "loans": _generate_loans(has_loan_default, branch),
        "relationship": {
            "customerId": f"MB-CUS-{uuid.uuid4().hex[:8].upper()}",
            "since": rel_since,
            "tier": tier,
            "segment": segment,
            "branch": branch,
            "relationshipManager": f"{rm_first} {rm_last}",
            "status": "blacklisted" if is_active else "cleared",
            "previousStatus": "active",
            "blacklistedAt": flagged_date,
        },
        "kyc": {
            "level": random.choice(["full", "basic", "enhanced"]),
            "verifiedAt": _rand_date(2015, 2023),
            "idType": random.choice(["national_id", "passport", "drivers_license"]),
            "idNumber": _rand_national_id(),
            "riskRating": "high" if risk_score > 0.7 else ("medium" if risk_score > 0.4 else "low"),
            "lastReviewedAt": _rand_date(2023, 2025),
            "pepStatus": random.random() < 0.02,
            "fatcaReportable": random.random() < 0.01,
        },
        "negativeReasons": reasons,
        "negativeReasonCodes": [r["code"] for r in reasons],
        "riskTags": tags,
        "riskScore": risk_score,
        "watchlistSources": watchlist_sources,
        "watchlistSourceNames": list({s["source"] for s in watchlist_sources}),
        "auditTrail": [
            {
                "action": "added_to_negative_list",
                "performedBy": "SYSTEM_CDC",
                "timestamp": flagged_date,
                "notes": f"Auto-ingested from mainframe batch — {reasons[0]['code'].lower().replace('_', ' ')} trigger",
            },
        ],
        "isActive": is_active,
        "createdAt": flagged_date,
        "updatedAt": now,
        "sourceSystem": "IBM_MAINFRAME_DB2",
    }


# ── Company Entry Generator ─────────────────────────────────────────────────


def _generate_company_entry(idx: int, category: str, is_repeat: bool, is_resolved: bool) -> dict:
    """Generate a single company negative list entry."""
    prefix = random.choice(COMPANY_PREFIXES)
    if random.random() < 0.3:
        prefix = random.choice(FILIPINO_FAMILY + CHINESE_FILIPINO_FAMILY)
    suffix = random.choice(COMPANY_SUFFIXES)
    company_name = f"{prefix} {suffix}"

    aliases = []
    if random.random() < 0.4:
        aliases.append(prefix)
    if random.random() < 0.3:
        alt_suffix = random.choice(COMPANY_SUFFIXES)
        if alt_suffix != suffix:
            aliases.append(f"{prefix} {alt_suffix}")

    flagged_date = _rand_date(2018, 2025)
    num_reasons = random.randint(2, 3) if is_repeat else 1
    reasons = _pick_negative_reasons(category, num_reasons)
    reason_codes = [r["code"] for r in reasons]
    watchlist_sources = _pick_watchlist_sources(reason_codes)
    risk_score = _compute_risk_score(reasons, watchlist_sources)
    tags = _risk_tags(reasons, risk_score)

    is_active = not is_resolved
    if is_resolved:
        for r in reasons:
            r["status"] = "resolved"

    branch = random.choice(MB_BRANCHES)
    now = datetime.now(timezone.utc)
    rel_since = _rand_date(2005, 2020)

    return {
        "entityId": f"MB-NEG-{4750 + idx + 1:06d}",
        "entityType": "company",
        "fullName": company_name,
        "aliases": aliases,
        "dateOfBirth": None,
        "gender": None,
        "phone": _rand_phone(),
        "email": f"info@{prefix.lower().replace(' ', '')}.com.ph",
        "civilStatus": None,
        "nationality": "Philippines",
        "identifiers": {
            "nationalId": None,
            "tin": _rand_tin(),
            "sssNo": None,
            "gsisNo": None,
            "passportNo": None,
            "driversLicense": None,
        },
        "addresses": [_rand_address()],
        "accounts": [
            {
                "type": "checking",
                "number": _rand_account_number(),
                "productName": random.choice(CHECKING_PRODUCTS),
                "status": random.choice(["active", "frozen", "closed"]),
                "branch": branch,
                "openedAt": _rand_date(2005, 2020),
                "closedAt": None,
                "lastBalance": round(random.uniform(0, 2000000), 2),
                "currency": "PHP",
            },
            {
                "type": "savings",
                "number": _rand_account_number(),
                "productName": random.choice(SAVINGS_PRODUCTS),
                "status": random.choice(["active", "frozen", "closed"]),
                "branch": branch,
                "openedAt": _rand_date(2005, 2020),
                "closedAt": None,
                "lastBalance": round(random.uniform(0, 5000000), 2),
                "currency": "PHP",
            },
        ],
        "loans": _generate_loans(any(r["code"] == "LOAN_DEFAULT" for r in reasons), branch),
        "relationship": {
            "customerId": f"MB-CUS-{uuid.uuid4().hex[:8].upper()}",
            "since": rel_since,
            "tier": random.choice(["standard", "silver", "gold", "platinum"]),
            "segment": random.choice(["sme", "corporate"]),
            "branch": branch,
            "relationshipManager": f"{random.choice(FILIPINO_MALE_FIRST)} {random.choice(FILIPINO_FAMILY)}",
            "status": "blacklisted" if is_active else "cleared",
            "previousStatus": "active",
            "blacklistedAt": flagged_date,
        },
        "kyc": {
            "level": random.choice(["enhanced", "full"]),
            "verifiedAt": _rand_date(2010, 2020),
            "idType": "sec_registration",
            "idNumber": f"SEC-{uuid.uuid4().hex[:10].upper()}",
            "riskRating": "high" if risk_score > 0.7 else ("medium" if risk_score > 0.4 else "low"),
            "lastReviewedAt": _rand_date(2023, 2025),
            "pepStatus": False,
            "fatcaReportable": False,
        },
        "negativeReasons": reasons,
        "negativeReasonCodes": [r["code"] for r in reasons],
        "riskTags": tags,
        "riskScore": risk_score,
        "watchlistSources": watchlist_sources,
        "watchlistSourceNames": list({s["source"] for s in watchlist_sources}),
        "auditTrail": [
            {
                "action": "added_to_negative_list",
                "performedBy": "SYSTEM_CDC",
                "timestamp": flagged_date,
                "notes": f"Auto-ingested from mainframe batch — {reasons[0]['code'].lower().replace('_', ' ')} trigger",
            },
        ],
        "isActive": is_active,
        "createdAt": flagged_date,
        "updatedAt": now,
        "sourceSystem": "IBM_MAINFRAME_DB2",
    }


# ── Batch Data Generation ───────────────────────────────────────────────────


def generate_all_entries() -> list[dict]:
    """
    Generate 5,000 negative list entries with the required distribution:
    - ~95% person, ~5% company
    - ~60% loan defaults, ~25% CC, ~10% fraud, ~5% AML
    - ~30% repeat offenders (multiple reasons)
    - ~15% resolved (isActive: false)
    """
    random.seed(42)  # Reproducible for demo

    num_persons = int(TOTAL_ENTRIES * 0.95)  # 4750
    num_companies = TOTAL_ENTRIES - num_persons  # 250

    # Category distribution
    categories_pool: list[str] = (
        ["loan"] * 60 +
        ["cc"] * 25 +
        ["fraud"] * 10 +
        ["aml"] * 5
    )

    entries: list[dict] = []
    print(f"Generating {TOTAL_ENTRIES} entries...")

    for i in range(num_persons):
        category = random.choice(categories_pool)
        is_repeat = random.random() < 0.30
        is_resolved = random.random() < 0.15
        entry = _generate_person_entry(i, category, is_repeat, is_resolved)
        entries.append(entry)

        if (i + 1) % 500 == 0:
            print(f"  Generated {i + 1}/{TOTAL_ENTRIES} person entries...")

    print(f"  Generated {num_persons} person entries.")

    for i in range(num_companies):
        category = random.choice(categories_pool)
        is_repeat = random.random() < 0.30
        is_resolved = random.random() < 0.15
        entry = _generate_company_entry(i, category, is_repeat, is_resolved)
        entries.append(entry)

    print(f"  Generated {num_companies} company entries.")
    print(f"Total entries: {len(entries)}")

    # Shuffle so persons and companies are interleaved
    random.shuffle(entries)
    return entries


# ── Voyage AI Embedding ──────────────────────────────────────────────────────


async def generate_embeddings_batch(
    texts: list[str],
    http_client: httpx.AsyncClient,
) -> list[list[float]]:
    """Call Voyage AI for a single batch (<= 128 inputs). Returns list of embeddings."""
    resp = await http_client.post(
        VOYAGE_ENDPOINT,
        headers={
            "Authorization": f"Bearer {VOYAGE_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "input": texts,
            "model": VOYAGE_MODEL,
            "input_type": "document",
        },
        timeout=120.0,
    )
    resp.raise_for_status()
    data = resp.json()["data"]
    # Voyage returns embeddings in order of input
    return [item["embedding"] for item in data]


async def embed_all_entries(entries: list[dict]) -> None:
    """Generate Voyage AI embeddings for all entries, batched at 128 per call."""
    texts = [serialize_for_embedding(e) for e in entries]
    total_batches = (len(texts) + VOYAGE_BATCH_SIZE - 1) // VOYAGE_BATCH_SIZE

    print(f"\nGenerating Voyage AI embeddings ({len(texts)} documents, {total_batches} batches)...")

    async with httpx.AsyncClient() as client:
        for batch_idx in range(total_batches):
            start = batch_idx * VOYAGE_BATCH_SIZE
            end = min(start + VOYAGE_BATCH_SIZE, len(texts))
            batch_texts = texts[start:end]

            retries = 0
            max_retries = 5
            while True:
                try:
                    embeddings = await generate_embeddings_batch(batch_texts, client)
                    for i, emb in enumerate(embeddings):
                        entries[start + i]["embedding"] = emb
                    break
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 429 and retries < max_retries:
                        retries += 1
                        wait = 2 ** retries
                        print(f"  Rate limited. Retrying batch {batch_idx + 1} in {wait}s (attempt {retries}/{max_retries})...")
                        await asyncio.sleep(wait)
                    else:
                        raise
                except (httpx.ReadTimeout, httpx.ConnectTimeout) as e:
                    if retries < max_retries:
                        retries += 1
                        wait = 2 ** retries
                        print(f"  Timeout on batch {batch_idx + 1}. Retrying in {wait}s (attempt {retries}/{max_retries})...")
                        await asyncio.sleep(wait)
                    else:
                        raise

            print(f"  Embedded batch {batch_idx + 1}/{total_batches} ({end}/{len(texts)} documents)")

            # Small delay between batches to respect rate limits
            if batch_idx < total_batches - 1:
                await asyncio.sleep(0.5)

    # Verify all entries have embeddings
    missing = sum(1 for e in entries if "embedding" not in e)
    if missing:
        print(f"  WARNING: {missing} entries missing embeddings!")
    else:
        print(f"  All {len(entries)} entries embedded successfully.")


# ── MongoDB Operations ───────────────────────────────────────────────────────


async def seed_database(entries: list[dict]) -> None:
    """Connect to Atlas, drop existing data, insert entries, create indexes."""

    print("\nConnecting to MongoDB Atlas...")
    client = AsyncMongoClient(
        MONGO_URI,
        tls=True,
        tlsCertificateKeyFile=TLS_CERT_PATH,
    )

    # Verify connection
    await client.admin.command("ping")
    print("  Connected to Atlas cluster.")

    db = client[DB_NAME]
    collection = db[COLLECTION_NAME]

    # Drop existing collection
    print(f"  Dropping existing '{COLLECTION_NAME}' collection...")
    await collection.drop()

    # Insert in batches of 500 for efficiency
    insert_batch_size = 500
    total = len(entries)
    print(f"  Inserting {total} documents...")

    for i in range(0, total, insert_batch_size):
        batch = entries[i : i + insert_batch_size]
        await collection.insert_many(batch)
        print(f"    Inserted {min(i + insert_batch_size, total)}/{total}")

    # Create standard indexes
    print("  Creating entityId index...")
    await collection.create_index("entityId", unique=True)

    print("  Creating supplementary indexes...")
    await collection.create_index("isActive")
    await collection.create_index("riskScore")
    await collection.create_index("negativeReasons.code")
    await collection.create_index("relationship.branch")
    await collection.create_index("updatedAt")

    # Create Atlas Search indexes
    print("\n  Creating Atlas Search fuzzy index...")
    try:
        await db.command({
            "createSearchIndexes": COLLECTION_NAME,
            "indexes": [FUZZY_INDEX],
        })
        print("    Fuzzy index created (building in background).")
    except Exception as e:
        if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
            print(f"    Fuzzy index already exists, skipping. ({e})")
        else:
            print(f"    Warning creating fuzzy index: {e}")

    print("  Creating Atlas Vector Search index...")
    try:
        await db.command({
            "createSearchIndexes": COLLECTION_NAME,
            "indexes": [VECTOR_INDEX],
        })
        print("    Vector index created (building in background).")
    except Exception as e:
        if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
            print(f"    Vector index already exists, skipping. ({e})")
        else:
            print(f"    Warning creating vector index: {e}")

    # Final stats
    doc_count = await collection.count_documents({})
    active_count = await collection.count_documents({"isActive": True})
    person_count = await collection.count_documents({"entityType": "person"})
    company_count = await collection.count_documents({"entityType": "company"})

    print(f"\n{'='*60}")
    print(f"  Seed complete!")
    print(f"  Total documents:  {doc_count:,}")
    print(f"  Active:           {active_count:,}")
    print(f"  Resolved:         {doc_count - active_count:,}")
    print(f"  Persons:          {person_count:,}")
    print(f"  Companies:        {company_count:,}")
    print(f"{'='*60}")

    client.close()


# ── Main ─────────────────────────────────────────────────────────────────────


async def main() -> None:
    start_time = time.time()

    print("=" * 60)
    print("  MB Negative List — Seed Script")
    print("=" * 60)

    # Step 1: Generate entries
    entries = generate_all_entries()

    # Step 2: Generate embeddings via Voyage AI
    await embed_all_entries(entries)

    # Step 3: Insert into MongoDB Atlas and create indexes
    await seed_database(entries)

    elapsed = time.time() - start_time
    minutes = int(elapsed // 60)
    seconds = elapsed % 60
    print(f"\nTotal time: {minutes}m {seconds:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
