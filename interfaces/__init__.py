"""
PT Assist Interfaces

This package contains the user interfaces for the PT Assistant:
- clinic.py: the clinic app (the therapist side, under /therapist)
- patient_portal.py: the patient service and front page
- vercel_app.py: both, as one hosted app (the Vercel demo)
- cli.py: Command-line interface
"""

from .cli import main as cli_main

__all__ = ['cli_main']
