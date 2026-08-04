"""Syllabus banks shared by government, banking and railway exams.

Kept in one module so that a syllabus correction lands in a single place
instead of being duplicated across a dozen exam definitions. The leading
underscore keeps the registry's auto-discovery from treating this as an exam.
"""

from __future__ import annotations

from ..base import chapters

REASONING = chapters(
    ("Analogy and Classification", ["Semantic analogy", "Number analogy", "Odd one out"], 1.0),
    ("Series", ["Number series", "Alphabet series", "Missing term"], 1.2),
    ("Coding-Decoding", ["Letter coding", "Number coding", "Substitution coding", "Conditional coding"], 1.2),
    ("Blood Relations", ["Family tree", "Coded relations"], 0.8),
    ("Direction and Distance", ["Direction sense", "Shortest distance", "Turns and displacement"], 0.8),
    ("Seating Arrangement", ["Linear arrangement", "Circular arrangement", "Square arrangement"], 1.4),
    ("Puzzles", ["Floor puzzles", "Scheduling puzzles", "Box puzzles", "Categorised puzzles"], 1.4),
    ("Syllogism", ["Two statement syllogism", "Possibility cases", "Reverse syllogism"], 1.0),
    ("Inequality", ["Direct inequality", "Coded inequality"], 1.0),
    ("Order and Ranking", ["Position in a row", "Rank from top and bottom"], 0.8),
    ("Data Sufficiency", ["Two statement sufficiency", "Three statement sufficiency"], 0.8),
    ("Input-Output", ["Word based machine input", "Number based machine input"], 0.8),
    ("Statement and Conclusion", ["Course of action", "Cause and effect", "Assumption and inference"], 0.8),
    ("Non-Verbal Reasoning", ["Mirror and water images", "Paper folding and cutting", "Embedded figures", "Figure series"], 1.0),
    ("Venn Diagrams", ["Set representation", "Logical Venn"], 0.6),
)

QUANT_ARITHMETIC = chapters(
    ("Number System", ["Divisibility rules", "HCF and LCM", "Remainder theorem", "Unit digit", "Factors"], 1.2),
    ("Simplification and Approximation", ["BODMAS", "Surds and indices", "Square and cube roots"], 1.0),
    ("Percentage", ["Percentage change", "Successive percentage", "Application in other topics"], 1.2),
    ("Ratio and Proportion", ["Simple ratio", "Compound ratio", "Partnership", "Mixture and alligation"], 1.2),
    ("Average", ["Simple average", "Weighted average", "Average of series"], 1.0),
    ("Profit, Loss and Discount", ["Cost and selling price", "Successive discount", "Marked price", "Dishonest dealer"], 1.2),
    ("Simple and Compound Interest", ["SI formula", "CI formula", "Difference between SI and CI", "Instalments"], 1.2),
    ("Time, Speed and Distance", ["Relative speed", "Trains", "Boats and streams", "Races"], 1.2),
    ("Time and Work", ["Work efficiency", "Pipes and cisterns", "Wages"], 1.2),
    ("Mensuration", ["Area and perimeter of 2D figures", "Volume and surface area of 3D solids"], 1.0),
    ("Geometry", ["Triangles", "Circles", "Quadrilaterals", "Lines and angles", "Similarity and congruence"], 1.0),
    ("Trigonometry", ["Trigonometric ratios", "Identities", "Heights and distances"], 0.8),
    ("Algebra", ["Linear equations", "Quadratic equations", "Algebraic identities", "Polynomials"], 1.0),
    ("Data Interpretation", ["Tables", "Bar graphs", "Line graphs", "Pie charts", "Caselet", "Mixed graphs"], 1.4),
    ("Number Series", ["Missing number series", "Wrong number series"], 1.0),
    ("Quadratic Comparison", ["Comparison of two quadratic equations"], 0.8),
    ("Probability and Permutation", ["Basic probability", "Dice and cards", "Arrangements and selections"], 0.8),
)

ENGLISH = chapters(
    ("Reading Comprehension", ["Central idea", "Inference based questions", "Vocabulary in context", "Tone of the passage"], 1.6),
    ("Grammar and Error Detection", ["Subject-verb agreement", "Tenses", "Prepositions", "Articles", "Modifiers", "Spotting errors"], 1.4),
    ("Sentence Improvement", ["Phrase replacement", "Sentence correction"], 1.0),
    ("Fill in the Blanks", ["Single filler", "Double filler", "Cloze test"], 1.2),
    ("Para Jumbles", ["Sentence rearrangement", "Para completion"], 1.0),
    ("Vocabulary", ["Synonyms", "Antonyms", "One word substitution", "Spelling check"], 1.2),
    ("Idioms and Phrases", ["Common idioms", "Phrasal verbs"], 1.0),
    ("Active and Passive Voice", ["Voice conversion"], 0.6),
    ("Direct and Indirect Speech", ["Narration change"], 0.6),
    ("Sentence Connectors", ["Connector based sentence formation"], 0.6),
)

GENERAL_AWARENESS = chapters(
    ("Indian History", ["Ancient India", "Medieval India", "Modern India", "Freedom struggle"], 1.2),
    ("Indian Polity", ["Constitution and its features", "Fundamental rights and duties", "Parliament", "Judiciary", "Amendments"], 1.2),
    ("Geography", ["Physical geography of India", "Rivers and mountains", "Climate", "World geography basics"], 1.0),
    ("Indian Economy", ["Basic economic concepts", "Budget and taxation", "Banking and finance", "Economic schemes"], 1.0),
    ("General Science", ["Physics basics", "Chemistry basics", "Biology basics", "Everyday science"], 1.2),
    ("Static General Knowledge", ["Books and authors", "Awards and honours", "Important days", "Dances and festivals", "Organisations and headquarters"], 1.0),
    ("Current Affairs", ["National events", "International events", "Sports", "Appointments", "Schemes and initiatives"], 1.4),
    ("Art and Culture", ["Classical dances", "Music forms", "Monuments", "UNESCO sites"], 0.8),
)

COMPUTER_AWARENESS = chapters(
    ("Computer Fundamentals", ["Generations of computers", "Input and output devices", "Memory types"], 1.0),
    ("Operating System and Software", ["OS functions", "System vs application software", "Shortcut keys"], 1.0),
    ("MS Office", ["MS Word", "MS Excel", "MS PowerPoint"], 1.0),
    ("Networking and Internet", ["LAN and WAN", "Protocols", "Browsers and search engines", "Email"], 1.0),
    ("Database and DBMS Basics", ["DBMS concepts", "Types of keys"], 0.6),
    ("Cyber Security", ["Malware types", "Firewalls", "Safe practices"], 0.8),
    ("Abbreviations and Terminology", ["Common computer abbreviations"], 0.8),
)

GENERAL_SCIENCE = chapters(
    ("Physics", ["Motion and force", "Work and energy", "Light and sound", "Electricity and magnetism", "Units and measurement"], 1.2),
    ("Chemistry", ["Matter and its states", "Atoms and molecules", "Acids, bases and salts", "Metals and non-metals", "Carbon compounds"], 1.2),
    ("Biology", ["Cell and tissues", "Human body systems", "Nutrition and health", "Plant life", "Diseases"], 1.2),
    ("Environmental Science", ["Ecosystem", "Pollution", "Natural resources", "Climate change"], 0.8),
)

FINANCIAL_AWARENESS = chapters(
    ("Banking Basics", ["Types of banks", "RBI functions", "Monetary policy tools", "NPA and CRAR"], 1.4),
    ("Financial Markets", ["Money market instruments", "Capital market", "SEBI", "Mutual funds"], 1.0),
    ("Banking Products and Services", ["Deposit accounts", "Loans and advances", "Priority sector lending", "Negotiable instruments"], 1.0),
    ("Digital Banking and Payments", ["UPI", "NEFT, RTGS and IMPS", "Payment banks", "Digital wallets"], 1.0),
    ("Financial Inclusion and Schemes", ["PMJDY", "Mudra Yojana", "Insurance schemes", "Pension schemes"], 1.0),
    ("International Financial Institutions", ["IMF", "World Bank", "ADB", "NDB"], 0.8),
)
