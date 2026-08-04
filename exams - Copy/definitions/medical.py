"""Medical entrance exams."""

from __future__ import annotations

from ...models.enums import Difficulty, Language, QuestionType
from ..base import ExamPattern, SectionSpec, chapters
from ..registry import register

_PHYSICS = chapters(
    ("Physics and Measurement", ["Units and dimensions", "Significant figures", "Error analysis"], 0.6),
    ("Kinematics", ["Motion in a straight line", "Motion in a plane", "Projectile motion", "Relative velocity"], 1.0),
    ("Laws of Motion", ["Newton's laws", "Friction", "Circular motion", "Free body diagrams"], 1.0),
    ("Work, Energy and Power", ["Work-energy theorem", "Conservation of energy", "Collisions", "Power"], 1.0),
    ("Rotational Motion", ["Centre of mass", "Torque", "Moment of inertia", "Angular momentum", "Rolling motion"], 1.0),
    ("Gravitation", ["Newton's law of gravitation", "Gravitational potential energy", "Escape velocity", "Satellite motion"], 0.8),
    ("Properties of Solids and Liquids", ["Elasticity", "Pressure and Pascal's law", "Viscosity", "Bernoulli's principle", "Surface tension"], 1.0),
    ("Thermodynamics", ["Zeroth and first law", "Heat engines", "Second law", "Carnot cycle"], 1.0),
    ("Kinetic Theory of Gases", ["Ideal gas equation", "Degrees of freedom", "Mean free path", "Specific heats"], 0.8),
    ("Oscillations and Waves", ["SHM", "Simple pendulum", "Wave motion", "Superposition", "Beats", "Doppler effect"], 1.2),
    ("Electrostatics", ["Coulomb's law", "Electric field and potential", "Gauss's law", "Capacitors", "Dielectrics"], 1.4),
    ("Current Electricity", ["Ohm's law", "Resistivity", "Kirchhoff's laws", "Wheatstone bridge", "Potentiometer"], 1.4),
    ("Magnetic Effects of Current and Magnetism", ["Biot-Savart law", "Ampere's law", "Moving charge in a field", "Magnetic dipole", "Earth's magnetism"], 1.2),
    ("Electromagnetic Induction and AC", ["Faraday's law", "Lenz's law", "Self and mutual inductance", "LCR circuits", "Transformers"], 1.2),
    ("Electromagnetic Waves", ["Displacement current", "EM spectrum", "Properties of EM waves"], 0.5),
    ("Optics", ["Reflection and refraction", "Lenses and mirrors", "Optical instruments", "Interference", "Diffraction", "Polarisation"], 1.4),
    ("Dual Nature of Matter and Radiation", ["Photoelectric effect", "de Broglie wavelength", "Matter waves"], 0.8),
    ("Atoms and Nuclei", ["Bohr model", "Hydrogen spectrum", "Radioactivity", "Mass defect and binding energy", "Nuclear fission and fusion"], 1.0),
    ("Electronic Devices", ["Semiconductors", "p-n junction diode", "Rectifiers", "Logic gates", "Transistors"], 1.0),
    ("Experimental Skills", ["Vernier callipers", "Screw gauge", "Metre bridge", "Ohm's law experiment"], 0.5),
)

_CHEMISTRY = chapters(
    ("Some Basic Concepts of Chemistry", ["Mole concept", "Stoichiometry", "Empirical and molecular formula", "Concentration terms"], 0.8),
    ("Structure of Atom", ["Bohr model", "Quantum numbers", "Orbitals", "Electronic configuration", "Aufbau principle"], 1.0),
    ("Classification of Elements and Periodicity", ["Periodic trends", "Ionisation enthalpy", "Electronegativity", "Atomic radius"], 0.8),
    ("Chemical Bonding and Molecular Structure", ["VSEPR theory", "Hybridisation", "Molecular orbital theory", "Hydrogen bonding", "Dipole moment"], 1.4),
    ("Thermodynamics", ["Enthalpy", "Entropy", "Gibbs energy", "Hess's law", "Spontaneity"], 1.0),
    ("Equilibrium", ["Le Chatelier's principle", "Kc and Kp", "Ionic equilibrium", "pH and buffers", "Solubility product"], 1.2),
    ("Redox Reactions and Electrochemistry", ["Oxidation number", "Balancing redox equations", "Nernst equation", "Conductance", "Electrolysis", "Batteries"], 1.2),
    ("Chemical Kinetics", ["Rate law", "Order and molecularity", "Integrated rate equations", "Arrhenius equation", "Half-life"], 1.0),
    ("Solutions", ["Colligative properties", "Raoult's law", "Osmotic pressure", "van't Hoff factor"], 1.0),
    ("p-Block Elements", ["Group 13 to 18 trends", "Boron and aluminium compounds", "Oxides of nitrogen", "Interhalogens", "Noble gases"], 1.2),
    ("d- and f-Block Elements", ["Transition element trends", "Lanthanoid contraction", "KMnO4 and K2Cr2O7", "Magnetic properties"], 1.0),
    ("Coordination Compounds", ["Nomenclature", "Werner's theory", "Crystal field theory", "Isomerism", "Applications"], 1.2),
    ("Organic Chemistry: Basic Principles", ["IUPAC nomenclature", "Inductive and resonance effects", "Reaction intermediates", "Isomerism"], 1.4),
    ("Hydrocarbons", ["Alkanes", "Alkenes", "Alkynes", "Aromatic substitution", "Markovnikov rule"], 1.2),
    ("Haloalkanes and Haloarenes", ["SN1 and SN2", "Elimination reactions", "Aryl halide reactivity"], 1.0),
    ("Alcohols, Phenols and Ethers", ["Preparation and properties", "Acidity of phenols", "Williamson synthesis"], 1.0),
    ("Aldehydes, Ketones and Carboxylic Acids", ["Nucleophilic addition", "Aldol and Cannizzaro", "Acidity of carboxylic acids"], 1.2),
    ("Amines and Diazonium Salts", ["Basicity of amines", "Hofmann bromamide", "Diazotisation and coupling"], 0.8),
    ("Biomolecules", ["Carbohydrates", "Proteins", "Enzymes", "Vitamins", "Nucleic acids"], 1.0),
    ("Practical Chemistry", ["Salt analysis", "Detection of functional groups", "Titration principles"], 0.6),
)

_BOTANY = chapters(
    ("The Living World and Classification", ["Taxonomic hierarchy", "Five kingdom classification", "Nomenclature", "Viruses and lichens"], 1.0),
    ("Plant Kingdom", ["Algae", "Bryophytes", "Pteridophytes", "Gymnosperms", "Angiosperms", "Alternation of generations"], 1.0),
    ("Morphology of Flowering Plants", ["Root, stem and leaf modifications", "Inflorescence", "Flower structure", "Fruit and seed"], 1.0),
    ("Anatomy of Flowering Plants", ["Meristems", "Tissue systems", "Secondary growth", "Monocot vs dicot anatomy"], 1.0),
    ("Cell: The Unit of Life", ["Cell theory", "Prokaryotic and eukaryotic cells", "Cell organelles", "Cell membrane"], 1.2),
    ("Cell Cycle and Cell Division", ["Mitosis", "Meiosis", "Significance of meiosis", "Checkpoints"], 1.0),
    ("Photosynthesis in Higher Plants", ["Light reactions", "C3 and C4 pathways", "Photorespiration", "Limiting factors"], 1.2),
    ("Respiration in Plants", ["Glycolysis", "Krebs cycle", "ETS", "Respiratory quotient"], 1.0),
    ("Plant Growth and Development", ["Growth phases", "Plant hormones", "Photoperiodism", "Vernalisation"], 1.0),
    ("Transport in Plants and Mineral Nutrition", ["Water potential", "Transpiration", "Phloem transport", "Essential elements", "Nitrogen cycle"], 1.0),
    ("Sexual Reproduction in Flowering Plants", ["Microsporogenesis", "Megasporogenesis", "Pollination", "Double fertilisation", "Apomixis"], 1.2),
    ("Principles of Inheritance and Variation", ["Mendel's laws", "Linkage and recombination", "Sex determination", "Genetic disorders", "Pedigree analysis"], 1.4),
    ("Molecular Basis of Inheritance", ["DNA structure", "Replication", "Transcription", "Genetic code", "Translation", "Lac operon"], 1.4),
    ("Biotechnology and Its Applications", ["Recombinant DNA technology", "PCR", "Bt crops", "RNAi", "Gene therapy"], 1.2),
    ("Ecology and Environment", ["Population interactions", "Ecosystem energy flow", "Nutrient cycling", "Biodiversity", "Conservation"], 1.4),
)

_ZOOLOGY = chapters(
    ("Animal Kingdom", ["Basis of classification", "Non-chordate phyla", "Chordate classes", "Salient features"], 1.2),
    ("Structural Organisation in Animals", ["Animal tissues", "Frog morphology and anatomy"], 0.8),
    ("Biomolecules", ["Amino acids and proteins", "Enzyme action", "Enzyme inhibition", "Metabolic pools"], 1.0),
    ("Digestion and Absorption", ["Alimentary canal", "Digestive enzymes", "Absorption", "Disorders"], 1.0),
    ("Breathing and Exchange of Gases", ["Respiratory organs", "Transport of gases", "Oxygen dissociation curve", "Disorders"], 1.0),
    ("Body Fluids and Circulation", ["Blood composition", "Blood groups", "Cardiac cycle", "ECG", "Double circulation"], 1.2),
    ("Excretory Products and Elimination", ["Nephron structure", "Urine formation", "Counter-current mechanism", "Dialysis"], 1.0),
    ("Locomotion and Movement", ["Skeletal muscle contraction", "Skeletal system", "Joints", "Disorders"], 1.0),
    ("Neural Control and Coordination", ["Neuron and nerve impulse", "Synapse", "Central nervous system", "Reflex action"], 1.0),
    ("Chemical Coordination and Integration", ["Endocrine glands", "Hormone mechanism", "Hormonal disorders"], 1.0),
    ("Human Reproduction", ["Male and female reproductive systems", "Gametogenesis", "Menstrual cycle", "Embryonic development"], 1.2),
    ("Reproductive Health", ["Contraception", "STDs", "ART techniques", "Infertility"], 0.8),
    ("Evolution", ["Origin of life", "Evidences of evolution", "Hardy-Weinberg principle", "Natural selection", "Human evolution"], 1.2),
    ("Human Health and Disease", ["Immunity", "Vaccination", "Pathogens and diseases", "Cancer", "Drug abuse"], 1.2),
    ("Biotechnology Principles", ["Restriction enzymes", "Cloning vectors", "Bioreactors", "Downstream processing"], 1.0),
)

_MARKING = dict(marks_correct=4.0, marks_incorrect=-1.0)

register(
    ExamPattern(
        exam="NEET UG",
        slug="neet-ug",
        category="Medical Entrance",
        pattern_version="2025",
        total_time_minutes=180,
        sections=(
            SectionSpec("Physics", "Physics", 45, chapters=_PHYSICS, **_MARKING),
            SectionSpec("Chemistry", "Chemistry", 45, chapters=_CHEMISTRY, **_MARKING),
            SectionSpec("Botany", "Biology", 45, chapters=_BOTANY, **_MARKING),
            SectionSpec("Zoology", "Biology", 45, chapters=_ZOOLOGY, **_MARKING),
        ),
        languages=(Language.ENGLISH, Language.HINDI, Language.BILINGUAL),
        difficulty_mix={Difficulty.EASY: 0.35, Difficulty.MEDIUM: 0.45, Difficulty.HARD: 0.20},
        negative_marking_default=True,
        aliases=("neet", "neet ug 2025", "aipmt"),
        instructions=(
            "The test contains 180 single-correct multiple-choice questions carrying 720 marks.",
            "Each correct response earns 4 marks; each incorrect response deducts 1 mark.",
            "Unattempted questions carry no penalty.",
            "Only one option is correct for every question.",
        ),
        notes=(
            "Modelled on the 180-compulsory-question scheme. NTA has varied between "
            "optional Section B and fully compulsory papers across recent cycles."
        ),
    )
)
