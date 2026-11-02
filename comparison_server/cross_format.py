"""Common comparison view; each edition must be extracted from its OWN file.

For mixed inputs pipeline renders Word independently and reads that PDF. No
text, paragraph boundaries or table values are copied from the other edition.
"""

def prepare_pair(old, new):
    from .pdf_structure import logical_pdf
    return logical_pdf(old), logical_pdf(new)
