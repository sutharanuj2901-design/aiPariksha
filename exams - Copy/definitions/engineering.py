"""Engineering entrance exams."""

from __future__ import annotations

from ...models.enums import Difficulty, Language, QuestionType
from ..base import ExamPattern, SectionSpec, chapters
from ..registry import register
from .medical import _CHEMISTRY, _PHYSICS  # shared 11th/12th science syllabus

_MATHS = chapters(
    ("Sets, Relations and Functions", ["Types of relations", "Domain and range", "Composite and inverse functions"], 0.8),
    ("Complex Numbers and Quadratic Equations", ["Argand plane", "Modulus and argument", "Roots of unity", "Nature of roots"], 1.2),
    ("Matrices and Determinants", ["Properties of determinants", "Inverse of a matrix", "System of linear equations", "Adjoint"], 1.2),
    ("Permutations and Combinations", ["Fundamental principle of counting", "Circular permutations", "Selections with restrictions"], 1.0),
    ("Binomial Theorem", ["General and middle term", "Greatest coefficient", "Multinomial expansions"], 0.8),
    ("Sequences and Series", ["AP", "GP", "HP", "AM-GM inequality", "Sum of special series"], 1.0),
    ("Limits, Continuity and Differentiability", ["Standard limits", "L'Hopital-free techniques", "Continuity tests", "Rolle and Lagrange theorems"], 1.4),
    ("Differentiation and Applications", ["Chain rule", "Implicit differentiation", "Tangents and normals", "Maxima and minima", "Rate of change"], 1.4),
    ("Integral Calculus", ["Indefinite integrals", "Definite integral properties", "Integration by parts", "Area under curves"], 1.4),
    ("Differential Equations", ["Variable separable", "Homogeneous equations", "Linear differential equations"], 1.0),
    ("Coordinate Geometry: Straight Lines", ["Slope and intercepts", "Angle between lines", "Family of lines"], 1.0),
    ("Circles", ["Equation of a circle", "Tangents and normals", "Family of circles", "Radical axis"], 1.0),
    ("Conic Sections", ["Parabola", "Ellipse", "Hyperbola", "Eccentricity and directrix"], 1.2),
    ("Three Dimensional Geometry", ["Direction cosines", "Line and plane equations", "Shortest distance", "Angle between planes"], 1.2),
    ("Vector Algebra", ["Dot and cross product", "Scalar triple product", "Coplanarity"], 1.0),
    ("Statistics and Probability", ["Mean, median and mode", "Variance and standard deviation", "Conditional probability", "Bayes' theorem", "Binomial distribution"], 1.2),
    ("Trigonometry", ["Trigonometric identities", "Trigonometric equations", "Inverse trigonometric functions", "Heights and distances"], 1.2),
    ("Mathematical Reasoning", ["Statements and connectives", "Tautology and contradiction", "Negation"], 0.5),
)

_LANGS = (Language.ENGLISH, Language.HINDI, Language.BILINGUAL)

# JEE Main Paper 1: each subject splits into 20 MCQs (Section A) and 5
# compulsory numerical-value questions (Section B). Modelling these as separate
# sections is what lets the blueprint and scorer apply different question types
# and marking without any special-casing.
_MAIN_MCQ = dict(
    marks_correct=4.0,
    marks_incorrect=-1.0,
    question_types=(QuestionType.MCQ_SINGLE,),
)
_MAIN_NUM = dict(
    marks_correct=4.0,
    marks_incorrect=-1.0,
    question_types=(QuestionType.NUMERICAL,),
)

register(
    ExamPattern(
        exam="JEE Main",
        slug="jee-main",
        category="Engineering Entrance",
        pattern_version="2025",
        total_time_minutes=180,
        sections=(
            SectionSpec("Physics - Section A", "Physics", 20, chapters=_PHYSICS, **_MAIN_MCQ),
            SectionSpec("Physics - Section B", "Physics", 5, chapters=_PHYSICS, **_MAIN_NUM),
            SectionSpec("Chemistry - Section A", "Chemistry", 20, chapters=_CHEMISTRY, **_MAIN_MCQ),
            SectionSpec("Chemistry - Section B", "Chemistry", 5, chapters=_CHEMISTRY, **_MAIN_NUM),
            SectionSpec("Mathematics - Section A", "Mathematics", 20, chapters=_MATHS, **_MAIN_MCQ),
            SectionSpec("Mathematics - Section B", "Mathematics", 5, chapters=_MATHS, **_MAIN_NUM),
        ),
        languages=_LANGS,
        difficulty_mix={Difficulty.EASY: 0.25, Difficulty.MEDIUM: 0.50, Difficulty.HARD: 0.25},
        negative_marking_default=True,
        aliases=("jee mains", "jee main paper 1", "jee"),
        instructions=(
            "75 questions across Physics, Chemistry and Mathematics; 300 maximum marks.",
            "Section A holds 20 single-correct MCQs per subject; Section B holds 5 compulsory numerical-value questions per subject.",
            "Each correct response earns 4 marks; each incorrect response deducts 1 mark.",
            "Numerical answers should be rounded to the nearest integer unless stated otherwise.",
        ),
        notes="Section B was 10-choose-5 in earlier cycles; the current scheme uses 5 compulsory questions.",
    )
)

# JEE Advanced deliberately varies its pattern every year. The definition below
# is a representative Paper 1 shape used for practice, and the note says so.
_ADV_MULTI = dict(
    marks_correct=4.0,
    marks_incorrect=-2.0,
    partial_marks=1.0,
    question_types=(QuestionType.MCQ_MULTIPLE,),
)
_ADV_NUM = dict(
    marks_correct=4.0,
    marks_incorrect=0.0,
    question_types=(QuestionType.NUMERICAL,),
)
_ADV_SINGLE = dict(
    marks_correct=3.0,
    marks_incorrect=-1.0,
    question_types=(QuestionType.MCQ_SINGLE,),
)

register(
    ExamPattern(
        exam="JEE Advanced",
        slug="jee-advanced",
        category="Engineering Entrance",
        pattern_version="2025 (representative Paper 1)",
        total_time_minutes=180,
        sections=(
            SectionSpec("Physics - Multiple Correct", "Physics", 4, chapters=_PHYSICS, **_ADV_MULTI),
            SectionSpec("Physics - Numerical", "Physics", 6, chapters=_PHYSICS, **_ADV_NUM),
            SectionSpec("Physics - Single Correct", "Physics", 7, chapters=_PHYSICS, **_ADV_SINGLE),
            SectionSpec("Chemistry - Multiple Correct", "Chemistry", 4, chapters=_CHEMISTRY, **_ADV_MULTI),
            SectionSpec("Chemistry - Numerical", "Chemistry", 6, chapters=_CHEMISTRY, **_ADV_NUM),
            SectionSpec("Chemistry - Single Correct", "Chemistry", 7, chapters=_CHEMISTRY, **_ADV_SINGLE),
            SectionSpec("Mathematics - Multiple Correct", "Mathematics", 4, chapters=_MATHS, **_ADV_MULTI),
            SectionSpec("Mathematics - Numerical", "Mathematics", 6, chapters=_MATHS, **_ADV_NUM),
            SectionSpec("Mathematics - Single Correct", "Mathematics", 7, chapters=_MATHS, **_ADV_SINGLE),
        ),
        languages=(Language.ENGLISH, Language.HINDI),
        difficulty_mix={Difficulty.EASY: 0.10, Difficulty.MEDIUM: 0.40, Difficulty.HARD: 0.50},
        negative_marking_default=True,
        aliases=("jee adv", "iit jee", "jee advanced paper 1"),
        instructions=(
            "Multiple-correct questions award partial credit; select every correct option to earn full marks.",
            "Numerical-value questions carry no negative marking.",
            "Read each section's marking rules before attempting.",
        ),
        notes=(
            "JEE Advanced changes its question composition and marking every year by design. "
            "This is a practice-oriented representative structure, not a prediction of the "
            "upcoming paper. Verify the current scheme with the organising IIT."
        ),
    )
)
