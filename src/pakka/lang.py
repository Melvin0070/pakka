"""The language a deployment listens in: recogniser settings, the open acoustic model and its orthography.

Hindi is the default and its settings must not change: they are hashed into the replay cache key behind every
published Hindi number. A new language is a new entry here plus its tables in lexicon, normalise and render;
the lattice, the decision rule, the policy and the executor are shared.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Lang:
    code: str
    name: str
    script: re.Pattern[str]
    # Recognisers
    transcribe_languages: tuple[str, ...]
    domain_prompt: str
    script_prompt: str  # steers gpt-4o-transcribe to the right script; names no numbers
    sarvam_code: str
    verbx_code: str
    agent_instructions: str
    # Acoustic witness
    model_name: str
    unicode_form: Literal["NFC", "NFD"]  # how the model's vocabulary spells composed letters
    digit_words: tuple[tuple[str, ...], ...]  # per digit: native word(s), then English as the model spells it
    repeat_words: tuple[str, str]  # "double", "triple"
    spellings: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def model_dir(self) -> Path:
        return Path(os.environ.get("PAKKA_MODELS") or ROOT / "models") / self.code


HI = Lang(
    code="hi",
    name="Hindi",
    script=re.compile("[ऀ-ॿ]"),
    transcribe_languages=("hi", "en"),
    domain_prompt=(
        "A phone call in India in Hindi, English or both. The caller may state an amount in rupees "
        "(hazaar, lakh, sava, saadhe, paune, dedh, dhai), a date or weekday, or a 10-digit mobile number."
    ),
    script_prompt="यह भारत में एक फ़ोन कॉल है, हिंदी और English में।",
    sarvam_code="hi-IN",
    verbx_code="hi",
    agent_instructions=(
        "You are an assistant answering a phone call in India. Callers speak Hindi, English or a mix. "
        "When the caller states an amount, a date or a phone number, call log_commitment with those values."
    ),
    model_name="ai4bharat/indicconformer-hi-ctc (OpenVoiceOS ONNX)",
    unicode_form="NFD",  # splits precomposed nukta letters (ज़ -> ज + ़), which is how the vocabulary spells them
    digit_words=(
        ("शून्य", "ज़ीरो"),
        ("एक", "वन"),
        ("दो", "टू"),
        ("तीन", "थ्री"),
        ("चार", "फ़ोर"),
        ("पाँच", "फ़ाइव"),
        ("छह", "सिक्स"),
        ("सात", "सेवन"),
        ("आठ", "एट"),
        ("नौ", "नाइन"),
    ),  # fmt: skip
    repeat_words=("डबल", "ट्रिपल"),
    spellings={"छह": ("छः", "छे"), "रुपये": ("रुपए", "रुपय"), "तारीख": ("तारीख़",)},
)

TE = Lang(
    code="te",
    name="Telugu",
    script=re.compile("[ఀ-౿]"),
    transcribe_languages=("te", "en"),
    domain_prompt=(
        "A phone call in India in Telugu, English or both. The caller may state an amount in rupees "
        "(vandalu, velu, lakshalu, rendunnara, lakshannara), a date or weekday, or a 10-digit mobile number."
    ),
    script_prompt="ఇది భారతదేశంలో ఒక ఫోన్ కాల్, తెలుగు మరియు English లో.",
    sarvam_code="te-IN",
    verbx_code="te",
    agent_instructions=(
        "You are an assistant answering a phone call in India. Callers speak Telugu, English or a mix. "
        "When the caller states an amount, a date or a phone number, call log_commitment with those values."
    ),
    model_name="ai4bharat/indicconformer-te-ctc (OpenVoiceOS ONNX)",
    unicode_form="NFC",
    digit_words=(
        ("సున్నా", "సున్న", "జీరో"),
        ("ఒకటి", "వన్"),
        ("రెండు", "టూ"),
        ("మూడు", "త్రీ"),
        ("నాలుగు", "ఫోర్"),
        ("ఐదు", "ఫైవ్"),
        ("ఆరు", "సిక్స్"),
        ("ఏడు", "సెవెన్"),
        ("ఎనిమిది", "ఎయిట్"),
        ("తొమ్మిది", "నైన్"),
    ),  # fmt: skip
    repeat_words=("డబుల్", "ట్రిపుల్"),
    # How the Telugu model itself writes these loanwords, read off its decodes of the tuning speakers.
    spellings={"థౌజండ్": ("థౌసండ్",), "టూ": ("టు",), "డబుల్": ("డబల్",), "లాక్": ("ల్యాక్",)},
)


def state_dir() -> Path:
    """Where the process may write (bundles, cached posteriors). A read-only host points this at /tmp."""
    return Path(os.environ.get("PAKKA_STATE") or ROOT / "data")


LANGS = {lang.code: lang for lang in (HI, TE)}


def get(code: str | None = None) -> Lang:
    """The named language, or the one PAKKA_LANG selects (Hindi when unset)."""
    return LANGS[code or os.environ.get("PAKKA_LANG") or "hi"]
