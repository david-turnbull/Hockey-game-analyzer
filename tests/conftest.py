import os
import sys
import pytest

# Ensure the root folder is in the path for tests
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.append(project_root)

from app import create_app
from app.models.base import db as _db

@pytest.fixture
def app():
    """Create and configure a new Flask instance for testing."""
    app = create_app('testing')
    
    with app.app_context():
        _db.create_all()
        yield app
        _db.session.remove()
        _db.drop_all()

@pytest.fixture
def client(app):
    """A test client for the application."""
    return app.test_client()

@pytest.fixture
def db(app):
    """Provide test database session."""
    return _db
