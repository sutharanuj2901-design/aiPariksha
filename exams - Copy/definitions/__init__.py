"""Exam definition modules.

Every module in this package is auto-imported by ``exams.registry`` and is
expected to build one or more ``ExamPattern`` objects and ``register()`` them.

To add an exam: create ``my_exam.py`` here, describe the pattern as data, call
``register(...)``. Nothing else in the codebase changes.
"""
