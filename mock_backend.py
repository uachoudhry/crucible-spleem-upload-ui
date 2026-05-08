"""
Mock backend for previewing the UI without Crucible/Prefect dependencies.
"""
import logging

logger = logging.getLogger(__name__)


def lookup_user_by_email(email: str) -> dict:
    return {
        "name": "Test User",
        "orcid": "0000-0001-2345-6789",
        "projects": ["project-alpha", "project-beta", "Internal Research (CFN-12345)"],
    }


def lookup_sample(sample_name=None, sample_unique_id=None, project_id=None) -> dict:
    return {
        "unique_id": "sample-001-abc",
        "sample_name": sample_name or "Mock Sample",
        "description": "Type: thin film\nCreated: 2026-01-15\nMock sample for UI preview",
    }


def create_sample(sample_name, owner_orcid, project_id, description=None, sample_type=None) -> dict:
    return {
        "unique_id": "sample-new-xyz",
        "sample_name": sample_name,
    }


def print_sample_barcode(sample_unique_id, sample_name):
    logger.info(f"[MOCK] Would print barcode for {sample_unique_id}")


def check_existing_sessions(session_folder_path, orcid, project_id, instrument_name) -> list:
    return []
