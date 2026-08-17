"""Output artefacts: institutional workbook, evaluation form, dashboard, record."""

from .dashboard import write_dashboard  # noqa: F401
from .docform import write_evaluation_form  # noqa: F401
from .record import verify_record, write_record  # noqa: F401
from .workbook import write_workbook  # noqa: F401
